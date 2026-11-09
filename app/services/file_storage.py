"""Stored files and their references: the catalog (files_sql.py) and the blobs (blob_store.py).
A blob is written and synced before the catalog names it, and retired only after the catalog stops."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid
from typing import Callable, Iterator, Optional

from app.upload_limits import MAX_ATTACHMENT_BYTES
from app.db.blob_store import BlobSeal, StoredBlob
from app.db.file_schema import FILE_PREVIEW_VARIANTS
from app.db.file_session import begin_file_writer, connect_file_reader, live_blob_store
from app.db.session import after_recoverable_commit
from app.db.files_sql import (
    AttachmentSizeExceeded,
    delete_file_previews,
    delete_files,
    fetch_all_file_ids,
    fetch_all_file_metadata,
    fetch_all_file_previews,
    fetch_all_file_text_filters,
    fetch_all_file_texts,
    fetch_all_blob_ids,
    fetch_blob_ids_of_files,
    fetch_content_revisions,
    fetch_every_blob_id_of_files,
    fetch_file_text,
    fetch_file_metadata,
    fetch_file_preview,
    fetch_file,
    insert_file,
    replace_file_content_fields,
    update_file_name_fields,
    update_file_preview_storage_fields,
    update_file_storage_fields,
    upsert_file_preview,
    upsert_file_text,
    update_file_text_storage_fields,
)
from app.security.encryption import (
    get_encryption_service,
    get_encryption_service_with_token,
    is_encryption_required,
)
from app.services.file_kinds import FILE_FILTER_ANY
from app.services.file_registry import FileDetails, file_registry
from app.services.file_text_search import (
    is_searchable_file_name,
    FileTextStorage,
    KeptText,
    StoredFileText,
    StoredFilter,
    file_texts,
)
from app.services.input_errors import InputRejected
from app.services.note_store import store as note_store
from app.utils.file_names import MAX_FILE_NAME_CHARACTERS, replace_unsafe_filename_characters, split_extension

_ALLOWED_THUMBNAIL_KINDS = {"pdf", "image", "audio", "video", "text", "archive", "excalidraw", "other"}

EXCALIDRAW_MIME_TYPE = "application/vnd.excalidraw+json"
EXCALIDRAW_FILE_EXTENSION = ".excalidraw"
FILE_PREVIEW_MIME_TYPE = "image/svg+xml"
# Only files MetaList edits itself may be replaced in place; other attachments stay immutable.
_EDITABLE_THUMBNAIL_KINDS = {"excalidraw"}
_XML_DECLARATION_END = "?>"
# A new file ID is drawn at most this many times before giving up on finding
# one that no note or file already uses.
_UNIQUE_FILE_ID_ATTEMPTS = 100
# A blob no catalog row names is a crash's leftover once it is this old (maintainer, 2026-11-08).
_CRASH_LEFTOVER_GRACE_SECONDS = 60 * 60


class FileRevisionConflict(Exception):
    """The file changed since the client loaded it (another tab or window saved first)."""

    def __init__(self, *, file_id: str, expected_revision: int, current_revision: int) -> None:
        super().__init__(
            f"File {file_id} is at revision {current_revision}, not the expected revision {expected_revision}"
        )
        self.file_id = file_id
        self.expected_revision = expected_revision
        self.current_revision = current_revision


class FileNotEditable(ValueError):
    """The file kind does not support in-place updates or previews."""


class InvalidFileContent(ValueError):
    """Submitted file content or preview does not match the file kind."""


class FilePreviewMissing(Exception):
    """No rendered preview has been stored for this file and variant yet."""


@dataclass(frozen=True)
class FileReferenceRecord:
    id: str
    title: str
    original_filename: str
    mime_type: str
    size_bytes: int
    thumbnail_kind: str
    created_at: datetime
    updated_at: datetime
    content_revision: int


@dataclass(frozen=True)
class DownloadedFile:
    record: FileReferenceRecord
    content_bytes: bytes


@dataclass(frozen=True)
class FilePreview:
    file_id: str
    variant: str
    mime_type: str
    content_revision: int
    content_bytes: bytes


@dataclass(frozen=True)
class FileContentRange:
    """A file opened for reading a part of it: pieces yields exactly bytes start..start+length."""

    record: FileReferenceRecord
    start: int
    length: int
    pieces: Iterator[bytes]


@dataclass(frozen=True)
class _SealedBlob:
    """A blob just written, and its seal as the catalog stores it."""

    blob_id: str
    seal: bytes
    seal_nonce: Optional[bytes]
    seal_tag: Optional[bytes]


@dataclass(frozen=True)
class FileSnapshot:
    """An editable file's content and stored previews at one revision, kept for undo and discard."""

    file_id: str
    content_revision: int
    content_bytes: bytes
    # Empty when no previews were stored; otherwise one SVG per FILE_PREVIEW_VARIANTS entry.
    previews_by_variant: dict[str, bytes]


@dataclass(frozen=True)
class TrimUnusedFilesResult:
    deleted_count: int
    deleted_file_ids: list[str]


def bootstrap_file_registry() -> set[str]:
    with begin_file_writer():
        pass
    with connect_file_reader() as connection:
        rows = fetch_all_file_metadata(connection)
    file_ids: set[str] = set()
    thumbnail_kinds_by_id: dict[str, str] = {}
    encryption_service = _resolve_encryption_service(None)
    can_decrypt_encrypted_metadata = _coerce_encryption_service(encryption_service) is not None
    for row in rows:
        file_id = row["id"]
        if not isinstance(file_id, str) or file_id == "":
            raise TypeError(f"files.id must be a non-empty string, got {file_id!r}")
        file_ids.add(file_id)
        metadata_has_encryption = _field_has_encryption(
            nonce=row["metadata_encryption_nonce"],
            tag=row["metadata_encryption_tag"],
            file_id=file_id,
            field_name="metadata_json",
        )
        if metadata_has_encryption and not can_decrypt_encrypted_metadata:
            file_ids = set()
            for id_row in rows:
                row_file_id = id_row["id"]
                if not isinstance(row_file_id, str) or row_file_id == "":
                    raise TypeError(f"files.id must be a non-empty string, got {row_file_id!r}")
                file_ids.add(row_file_id)
            file_registry.replace_all(file_ids)
            return file_ids
        metadata_json = _decrypt_text_field(
            encryption_service=encryption_service,
            value=row["metadata_json"],
            nonce=row["metadata_encryption_nonce"],
            tag=row["metadata_encryption_tag"],
            field_name="metadata_json",
            file_id=file_id,
        )
        metadata = _parse_file_metadata(metadata_json, file_id=file_id)
        thumbnail_kind = metadata["thumbnail_kind"]
        if not isinstance(thumbnail_kind, str) or thumbnail_kind == "":
            raise TypeError(f"files.metadata_json thumbnail_kind invalid for file {file_id}")
        thumbnail_kinds_by_id[file_id] = thumbnail_kind
    if len(thumbnail_kinds_by_id) == len(file_ids):
        file_registry.replace_all_with_thumbnail_kinds(thumbnail_kinds_by_id)
    else:
        file_registry.replace_all(file_ids)
    return file_ids


def sweep_blob_leftovers() -> int:
    """Delete what a crash left in the blob folder. Needs no key, so it can run before unlock."""
    with connect_file_reader() as connection:
        referenced_blob_ids = fetch_all_blob_ids(connection)
    return live_blob_store().sweep(referenced_blob_ids=referenced_blob_ids, grace_seconds=_CRASH_LEFTOVER_GRACE_SECONDS)


def _load_file_details() -> dict[str, FileDetails]:
    """Every file's name and kind by id, decrypted (the file registry asks once, when
    notes are read, searched or filtered, which is only once the vault is unlocked)."""
    with connect_file_reader() as connection:
        rows = fetch_all_file_metadata(connection)
    encryption_service = _resolve_encryption_service(None)
    details: dict[str, FileDetails] = {}
    for row in rows:
        file_id = row["id"]
        title = _decrypt_text_field(
            encryption_service=encryption_service,
            value=row["title"],
            nonce=row["title_encryption_nonce"],
            tag=row["title_encryption_tag"],
            field_name="title",
            file_id=file_id,
        )
        metadata_json = _decrypt_text_field(
            encryption_service=encryption_service,
            value=row["metadata_json"],
            nonce=row["metadata_encryption_nonce"],
            tag=row["metadata_encryption_tag"],
            field_name="metadata_json",
            file_id=file_id,
        )
        thumbnail_kind = _parse_file_metadata(metadata_json, file_id=file_id)["thumbnail_kind"]
        assert isinstance(thumbnail_kind, str)
        details[file_id] = FileDetails(title=title, thumbnail_kind=thumbnail_kind)
    return details


file_registry.install_details_loader(_load_file_details)


def create_file(
    *,
    original_filename: str,
    mime_type: str,
    content_bytes: bytes,
    token: str,
) -> FileReferenceRecord:
    if not isinstance(original_filename, str) or original_filename == "":
        raise TypeError("original_filename must be a non-empty string")
    if not isinstance(mime_type, str) or mime_type == "":
        raise TypeError("mime_type must be a non-empty string")
    if not isinstance(content_bytes, bytes):
        raise TypeError(f"content_bytes must be bytes, got {type(content_bytes)}")
    if not isinstance(token, str) or token == "":
        raise TypeError("token must be a non-empty string")

    if len(content_bytes) > MAX_ATTACHMENT_BYTES:
        raise ValueError("Attachment exceeds the configured size limit")

    file_id = _generate_unique_file_id()
    title = Path(original_filename).name
    if title == "":
        raise ValueError("original_filename must resolve to a non-empty basename")

    metadata = {
        "original_filename": title,
        "mime_type": mime_type,
        "size_bytes": len(content_bytes),
        "thumbnail_kind": _derive_thumbnail_kind(mime_type=mime_type, original_filename=title),
    }
    metadata_json = json.dumps(metadata, separators=(",", ":"), ensure_ascii=False)

    encryption_service = _resolve_encryption_service(token)
    encrypted_title, title_nonce, title_tag = _encrypt_text_for_storage(
        encryption_service=encryption_service,
        plaintext=title,
    )
    encrypted_metadata, metadata_nonce, metadata_tag = _encrypt_text_for_storage(
        encryption_service=encryption_service,
        plaintext=metadata_json,
    )
    sealed = _write_blob(content_bytes=content_bytes, encryption_service=encryption_service)

    now = datetime.now(timezone.utc)
    with begin_file_writer() as connection:
        insert_file(
            connection,
            file_id=file_id,
            title=encrypted_title,
            title_encryption_nonce=title_nonce,
            title_encryption_tag=title_tag,
            metadata_json=encrypted_metadata,
            metadata_encryption_nonce=metadata_nonce,
            metadata_encryption_tag=metadata_tag,
            blob_id=sealed.blob_id,
            blob_seal=sealed.seal,
            blob_seal_encryption_nonce=sealed.seal_nonce,
            blob_seal_encryption_tag=sealed.seal_tag,
            created_at=now,
            updated_at=now,
        )

    file_registry.add_with_thumbnail_kind(file_id, thumbnail_kind=metadata["thumbnail_kind"], title=title)
    if is_searchable_file_name(title):
        # Its text, for search, beside the request (folder-import-and-file-previews.md).
        file_texts.refresh_in_background()
    return FileReferenceRecord(
        id=file_id,
        title=title,
        original_filename=metadata["original_filename"],
        mime_type=metadata["mime_type"],
        size_bytes=metadata["size_bytes"],
        thumbnail_kind=metadata["thumbnail_kind"],
        created_at=now,
        updated_at=now,
        content_revision=1,
    )


def get_file_reference_record(file_id: str, token: Optional[str]) -> FileReferenceRecord:
    if not isinstance(file_id, str) or file_id == "":
        raise TypeError("file_id must be a non-empty string")

    encryption_service = _resolve_encryption_service(token)
    with connect_file_reader() as connection:
        row = fetch_file_metadata(connection, file_id)
    if row is None:
        raise KeyError(f"File {file_id} not present")

    title = _decrypt_text_field(
        encryption_service=encryption_service,
        value=row["title"],
        nonce=row["title_encryption_nonce"],
        tag=row["title_encryption_tag"],
        field_name="title",
        file_id=file_id,
    )
    metadata_json = _decrypt_text_field(
        encryption_service=encryption_service,
        value=row["metadata_json"],
        nonce=row["metadata_encryption_nonce"],
        tag=row["metadata_encryption_tag"],
        field_name="metadata_json",
        file_id=file_id,
    )
    metadata = _parse_file_metadata(metadata_json, file_id=file_id)
    created_at = row["created_at"]
    updated_at = row["updated_at"]
    if not isinstance(created_at, datetime):
        raise TypeError(f"files.created_at must be datetime for file {file_id}")
    if not isinstance(updated_at, datetime):
        raise TypeError(f"files.updated_at must be datetime for file {file_id}")
    content_revision = row["content_revision"]
    assert isinstance(content_revision, int) and content_revision >= 1

    return FileReferenceRecord(
        id=file_id,
        title=title,
        original_filename=metadata["original_filename"],
        mime_type=metadata["mime_type"],
        size_bytes=metadata["size_bytes"],
        thumbnail_kind=metadata["thumbnail_kind"],
        created_at=created_at,
        updated_at=updated_at,
        content_revision=content_revision,
    )


def download_file(file_id: str, token: str) -> DownloadedFile:
    if not isinstance(token, str) or token == "":
        raise TypeError("token must be a non-empty string")
    return _read_stored_file(file_id, token)


def read_stored_file(file_id: str) -> DownloadedFile:
    """A file read with the session's key, as drawing a note reads files' details:
    for work no request asks for (an email's words in the search index)."""
    return _read_stored_file(file_id, None)


file_registry.install_content_reader(read_stored_file)


def _read_stored_file(file_id: str, token: Optional[str]) -> DownloadedFile:
    encryption_service = _resolve_encryption_service(token)
    row = _find_and_pin(lambda connection: fetch_file(connection, file_id))
    if row is None:
        raise KeyError(f"File {file_id} not present")
    try:
        seal = _open_seal(encryption_service=encryption_service, row=row, file_id=file_id)
        if seal.real_size > MAX_ATTACHMENT_BYTES:
            raise AttachmentSizeExceeded('Attachment exceeds the configured size limit')
        record = get_file_reference_record(file_id, token)
        content_bytes = live_blob_store().read_all(str(row["blob_id"]), seal)
    finally:
        live_blob_store().unpin([str(row["blob_id"])])
    return DownloadedFile(record=record, content_bytes=content_bytes)


def open_file_range(*, file_id: str, token: str, start: int, length: int) -> FileContentRange:
    """length bytes of a file from start, read a segment at a time, so memory stays small and a
    jump into a long video reads only that part. The caller must iterate pieces."""
    if not isinstance(token, str) or token == "":
        raise TypeError("token must be a non-empty string")
    encryption_service = _resolve_encryption_service(token)
    record = get_file_reference_record(file_id, token)
    store = live_blob_store()
    with store.lifecycle_lock:
        with connect_file_reader() as connection:
            row = fetch_file(connection, file_id)
        if row is None:
            raise KeyError(f"File {file_id} not present")
        seal = _open_seal(encryption_service=encryption_service, row=row, file_id=file_id)
        pieces = store.read_range(str(row["blob_id"]), seal, start=start, length=length)
    return FileContentRange(record=record, start=start, length=length, pieces=pieces)


def replace_file_content(
    *,
    file_id: str,
    content_bytes: bytes,
    expected_revision: int,
    token: str,
) -> FileReferenceRecord:
    """Replace an editable file's content if nobody saved since expected_revision."""
    if not isinstance(content_bytes, bytes):
        raise TypeError(f"content_bytes must be bytes, got {type(content_bytes)}")
    if not isinstance(expected_revision, int) or expected_revision < 1:
        raise TypeError(f"expected_revision must be a positive integer, got {expected_revision!r}")
    if not isinstance(token, str) or token == "":
        raise TypeError("token must be a non-empty string")
    if len(content_bytes) > MAX_ATTACHMENT_BYTES:
        raise ValueError("Attachment exceeds the configured size limit")

    record = get_file_reference_record(file_id, token)
    _require_editable(record)
    _validate_editable_content(thumbnail_kind=record.thumbnail_kind, content_bytes=content_bytes)
    if record.content_revision != expected_revision:
        raise FileRevisionConflict(
            file_id=file_id, expected_revision=expected_revision, current_revision=record.content_revision
        )

    encryption_service = _resolve_encryption_service(token)
    content_fields = _encrypt_replacement_content(
        record=record,
        content_bytes=content_bytes,
        encryption_service=encryption_service,
    )

    now = datetime.now(timezone.utc)
    with begin_file_writer() as connection:
        replaced_blob_ids = fetch_blob_ids_of_files(connection, [file_id])
        updated_rows = replace_file_content_fields(
            connection,
            file_id=file_id,
            expected_revision=expected_revision,
            updated_at=now,
            **content_fields,
        )
    if updated_rows != 1:
        _retire_blobs([str(content_fields["blob_id"])])
        current = get_file_reference_record(file_id, token)
        raise FileRevisionConflict(
            file_id=file_id, expected_revision=expected_revision, current_revision=current.content_revision
        )
    _retire_blobs(replaced_blob_ids)

    updated = get_file_reference_record(file_id, token)
    assert updated.content_revision == expected_revision + 1
    assert updated.size_bytes == len(content_bytes)
    return updated


def rename_file(*, file_id: str, name: str, token: str) -> FileReferenceRecord:
    """Give the file a new name, shown on its cards, found by search and used for its
    downloads (docs/ui/references.md, Renaming files). The extension stays: a name
    with another one is refused. Characters a file name can't hold become "-"."""
    if not isinstance(name, str):
        raise TypeError(f"name must be a string, got {type(name)}")
    if not isinstance(token, str) or token == "":
        raise TypeError("token must be a non-empty string")

    record = get_file_reference_record(file_id, token)
    stem, extension = split_extension(name.strip())
    _current_stem, current_extension = split_extension(record.original_filename)
    if extension != current_extension:
        raise InputRejected(f"A file's extension can't change: keep {current_extension or 'no extension'}.")
    clean_stem = replace_unsafe_filename_characters(stem).strip(" .")
    if clean_stem == "":
        raise InputRejected("A file name can't be blank.")
    new_name = f"{clean_stem}{extension}"
    if len(new_name) > MAX_FILE_NAME_CHARACTERS:
        raise InputRejected(f"A file name can be at most {MAX_FILE_NAME_CHARACTERS} characters long.")
    if new_name == record.original_filename and new_name == record.title:
        return record

    metadata = {
        "original_filename": new_name,
        "mime_type": record.mime_type,
        "size_bytes": record.size_bytes,
        "thumbnail_kind": record.thumbnail_kind,
    }
    metadata_json = json.dumps(metadata, separators=(",", ":"), ensure_ascii=False)
    encryption_service = _resolve_encryption_service(token)
    encrypted_title, title_nonce, title_tag = _encrypt_text_for_storage(
        encryption_service=encryption_service,
        plaintext=new_name,
    )
    encrypted_metadata, metadata_nonce, metadata_tag = _encrypt_text_for_storage(
        encryption_service=encryption_service,
        plaintext=metadata_json,
    )
    with begin_file_writer() as connection:
        updated_rows = update_file_name_fields(
            connection,
            file_id=file_id,
            title=encrypted_title,
            title_encryption_nonce=title_nonce,
            title_encryption_tag=title_tag,
            metadata_json=encrypted_metadata,
            metadata_encryption_nonce=metadata_nonce,
            metadata_encryption_tag=metadata_tag,
            updated_at=datetime.now(timezone.utc),
        )
    if updated_rows != 1:
        raise RuntimeError(f"Renaming file {file_id} changed {updated_rows} rows")

    file_registry.rename(file_id, title=new_name)
    # Search reads the names of the files a note shows (search_text.py).
    note_store.refresh_search_text_for_notes(note_store.note_ids_referencing({file_id}))
    renamed = get_file_reference_record(file_id, token)
    assert renamed.title == new_name and renamed.original_filename == new_name
    assert renamed.content_revision == record.content_revision
    return renamed


def _encrypt_replacement_content(
    *,
    record: FileReferenceRecord,
    content_bytes: bytes,
    encryption_service: object,
) -> dict[str, object]:
    metadata = {
        "original_filename": record.original_filename,
        "mime_type": record.mime_type,
        "size_bytes": len(content_bytes),
        "thumbnail_kind": record.thumbnail_kind,
    }
    metadata_json = json.dumps(metadata, separators=(",", ":"), ensure_ascii=False)
    encrypted_metadata, metadata_nonce, metadata_tag = _encrypt_text_for_storage(
        encryption_service=encryption_service,
        plaintext=metadata_json,
    )
    sealed = _write_blob(content_bytes=content_bytes, encryption_service=encryption_service)
    return {
        "metadata_json": encrypted_metadata,
        "metadata_encryption_nonce": metadata_nonce,
        "metadata_encryption_tag": metadata_tag,
        "blob_id": sealed.blob_id,
        "blob_seal": sealed.seal,
        "blob_seal_encryption_nonce": sealed.seal_nonce,
        "blob_seal_encryption_tag": sealed.seal_tag,
    }


def capture_file_snapshot(*, file_id: str, token: str) -> FileSnapshot:
    """Read an editable file's current content and previews so they can be written back later."""
    downloaded = download_file(file_id, token)
    _require_editable(downloaded.record)
    previews_by_variant: dict[str, bytes] = {}
    for variant in FILE_PREVIEW_VARIANTS:
        preview = find_file_preview(file_id=file_id, variant=variant, token=token)
        if preview is not None:
            previews_by_variant[variant] = preview.content_bytes
    if previews_by_variant and set(previews_by_variant) != set(FILE_PREVIEW_VARIANTS):
        raise RuntimeError(f"File {file_id} has previews for only some variants")
    return FileSnapshot(
        file_id=file_id,
        content_revision=downloaded.record.content_revision,
        content_bytes=downloaded.content_bytes,
        previews_by_variant=previews_by_variant,
    )


def restore_file_snapshot(*, snapshot: FileSnapshot, token: str) -> FileReferenceRecord:
    """Write a snapshot's content and previews back together as the file's next revision."""
    if not isinstance(snapshot, FileSnapshot):
        raise TypeError(f"snapshot must be a FileSnapshot, got {type(snapshot)}")
    if not isinstance(token, str) or token == "":
        raise TypeError("token must be a non-empty string")

    record = get_file_reference_record(snapshot.file_id, token)
    _require_editable(record)
    _validate_editable_content(thumbnail_kind=record.thumbnail_kind, content_bytes=snapshot.content_bytes)
    if snapshot.previews_by_variant and set(snapshot.previews_by_variant) != set(FILE_PREVIEW_VARIANTS):
        raise InvalidFileContent(f"Previews must include exactly these variants: {', '.join(FILE_PREVIEW_VARIANTS)}")
    for variant, svg_bytes in snapshot.previews_by_variant.items():
        _validate_svg_preview(svg_bytes=svg_bytes, variant=variant)

    encryption_service = _resolve_encryption_service(token)
    content_fields = _encrypt_replacement_content(
        record=record,
        content_bytes=snapshot.content_bytes,
        encryption_service=encryption_service,
    )
    sealed_previews = {
        variant: _write_blob(content_bytes=svg_bytes, encryption_service=encryption_service)
        for variant, svg_bytes in snapshot.previews_by_variant.items()
    }

    next_revision = record.content_revision + 1
    now = datetime.now(timezone.utc)
    with begin_file_writer() as connection:
        replaced_blob_ids = _content_and_preview_blob_ids(connection, snapshot.file_id)
        updated_rows = replace_file_content_fields(
            connection,
            file_id=snapshot.file_id,
            expected_revision=record.content_revision,
            updated_at=now,
            **content_fields,
        )
        if updated_rows != 1:
            raise RuntimeError(f"File {snapshot.file_id} changed while its snapshot was being restored")
        delete_file_previews(connection, snapshot.file_id)
        for variant, sealed in sealed_previews.items():
            upsert_file_preview(
                connection,
                file_id=snapshot.file_id,
                variant=variant,
                mime_type=FILE_PREVIEW_MIME_TYPE,
                blob_id=sealed.blob_id,
                blob_seal=sealed.seal,
                blob_seal_encryption_nonce=sealed.seal_nonce,
                blob_seal_encryption_tag=sealed.seal_tag,
                content_revision=next_revision,
                updated_at=now,
            )
    _retire_blobs(replaced_blob_ids)

    updated = get_file_reference_record(snapshot.file_id, token)
    assert updated.content_revision == next_revision
    assert updated.size_bytes == len(snapshot.content_bytes)
    return updated


def store_file_previews(
    *,
    file_id: str,
    previews_by_variant: dict[str, bytes],
    content_revision: int,
    token: str,
) -> FileReferenceRecord:
    """Store the light and dark SVG previews rendered from content_revision of an editable file."""
    if not isinstance(previews_by_variant, dict):
        raise TypeError(f"previews_by_variant must be a dict, got {type(previews_by_variant)}")
    if set(previews_by_variant.keys()) != set(FILE_PREVIEW_VARIANTS):
        raise InvalidFileContent(f"Previews must include exactly these variants: {', '.join(FILE_PREVIEW_VARIANTS)}")
    if not isinstance(content_revision, int) or content_revision < 1:
        raise TypeError(f"content_revision must be a positive integer, got {content_revision!r}")
    if not isinstance(token, str) or token == "":
        raise TypeError("token must be a non-empty string")

    record = get_file_reference_record(file_id, token)
    _require_editable(record)
    if record.content_revision != content_revision:
        raise FileRevisionConflict(
            file_id=file_id, expected_revision=content_revision, current_revision=record.content_revision
        )

    encryption_service = _resolve_encryption_service(token)
    sealed_previews: dict[str, _SealedBlob] = {}
    for variant in FILE_PREVIEW_VARIANTS:
        svg_bytes = previews_by_variant[variant]
        _validate_svg_preview(svg_bytes=svg_bytes, variant=variant)
        sealed_previews[variant] = _write_blob(content_bytes=svg_bytes, encryption_service=encryption_service)

    now = datetime.now(timezone.utc)
    replaced_blob_ids: list[str] = []
    with begin_file_writer() as connection:
        for variant, sealed in sealed_previews.items():
            current = fetch_file_preview(connection, file_id, variant)
            if current is not None:
                replaced_blob_ids.append(str(current["blob_id"]))
            upsert_file_preview(
                connection,
                file_id=file_id,
                variant=variant,
                mime_type=FILE_PREVIEW_MIME_TYPE,
                blob_id=sealed.blob_id,
                blob_seal=sealed.seal,
                blob_seal_encryption_nonce=sealed.seal_nonce,
                blob_seal_encryption_tag=sealed.seal_tag,
                content_revision=content_revision,
                updated_at=now,
            )
    _retire_blobs(replaced_blob_ids)
    return record


def get_file_preview(*, file_id: str, variant: str, token: str) -> FilePreview:
    preview = find_file_preview(file_id=file_id, variant=variant, token=token)
    if preview is None:
        raise FilePreviewMissing(f"No {variant} preview stored for file {file_id}")
    return preview


def find_file_preview(*, file_id: str, variant: str, token: str) -> Optional[FilePreview]:
    """The stored preview, or None when the diagram has not been rendered yet."""
    if not isinstance(file_id, str) or file_id == "":
        raise TypeError("file_id must be a non-empty string")
    if variant not in FILE_PREVIEW_VARIANTS:
        raise ValueError(f"variant must be one of {FILE_PREVIEW_VARIANTS}, got {variant!r}")
    if not isinstance(token, str) or token == "":
        raise TypeError("token must be a non-empty string")

    encryption_service = _resolve_encryption_service(token)
    row = _find_and_pin(lambda connection: fetch_file_preview(connection, file_id, variant))
    if row is None:
        return None
    content_bytes = _read_pinned_blob(encryption_service=encryption_service, row=row, file_id=file_id)
    mime_type = row["mime_type"]
    content_revision = row["content_revision"]
    assert mime_type == FILE_PREVIEW_MIME_TYPE, f"unexpected preview MIME type {mime_type!r}"
    assert isinstance(content_revision, int)
    return FilePreview(
        file_id=file_id,
        variant=variant,
        mime_type=mime_type,
        content_revision=content_revision,
        content_bytes=content_bytes,
    )


def unused_file_ids(*, kept_file_ids: frozenset[str]) -> set[str]:
    """Files no live note's text references, less those kept (what ⌘Z or a paste could
    bring back: unused_files.py)."""
    if not note_store.loaded:
        raise RuntimeError("Cannot list unused files before NoteStore hydration")
    return file_registry.list_ids() - note_store.referenced_target_ids() - kept_file_ids


def stored_size_of_files(file_ids: set[str]) -> int:
    """The bytes the files' content takes on disk, as stored (encrypted and padded or not)."""
    if not file_ids:
        return 0
    store = live_blob_store()
    with store.lifecycle_lock:
        with connect_file_reader() as connection:
            blob_ids = fetch_blob_ids_of_files(connection, sorted(file_ids))
        return sum(store.stored_size(blob_id) for blob_id in blob_ids)


def trim_unused_files(*, kept_file_ids: frozenset[str]) -> TrimUnusedFilesResult:
    deleted_ids = sorted(unused_file_ids(kept_file_ids=kept_file_ids))
    with begin_file_writer() as connection:
        deleted_blob_ids = fetch_every_blob_id_of_files(connection, deleted_ids)
        deleted_count = delete_files(connection, deleted_ids)
    _retire_blobs(deleted_blob_ids)
    if deleted_count != len(deleted_ids):
        raise RuntimeError(
            "File trim deleted unexpected number of rows: "
            f"expected={len(deleted_ids)} actual={deleted_count}"
        )
    file_registry.remove_many(set(deleted_ids))
    return TrimUnusedFilesResult(
        deleted_count=deleted_count,
        deleted_file_ids=deleted_ids,
    )


def encrypt_all_files_for_active_dek(*, encryption_service: object) -> int:
    service = _coerce_encryption_service(encryption_service)
    if service is None:
        raise RuntimeError("File encryption migration requires an active DEK")

    rewritten_count = 0
    replaced_blob_ids: list[str] = []
    with begin_file_writer() as connection:
        file_ids = fetch_all_file_ids(connection)
        for file_id in file_ids:
            row = fetch_file(connection, file_id)
            assert row is not None
            if _row_is_fully_encrypted(row):
                continue
            replaced_blob_ids.append(_rewrite_file_row(
                connection=connection,
                row=row,
                decrypt_encryption_service=service,
                encrypt_encryption_service=service,
            ))
            rewritten_count += 1
        replaced_blob_ids += _rewrite_file_previews(
            connection=connection,
            decrypt_encryption_service=service,
            encrypt_encryption_service=service,
        )
        replaced_blob_ids += _rewrite_file_texts(
            connection=connection,
            decrypt_encryption_service=service,
            encrypt_encryption_service=service,
        )
    _retire_blobs(replaced_blob_ids)
    return rewritten_count


def decrypt_all_files_for_plaintext(*, encryption_service: object) -> int:
    service = _coerce_encryption_service(encryption_service)
    if service is None:
        raise RuntimeError("File decryption migration requires an active DEK")

    rewritten_count = 0
    replaced_blob_ids: list[str] = []
    with begin_file_writer() as connection:
        file_ids = fetch_all_file_ids(connection)
        for file_id in file_ids:
            row = fetch_file(connection, file_id)
            assert row is not None
            if _row_is_fully_plaintext(row):
                continue
            replaced_blob_ids.append(_rewrite_file_row(
                connection=connection,
                row=row,
                decrypt_encryption_service=service,
                encrypt_encryption_service=None,
            ))
            rewritten_count += 1
        replaced_blob_ids += _rewrite_file_previews(
            connection=connection,
            decrypt_encryption_service=service,
            encrypt_encryption_service=None,
        )
        replaced_blob_ids += _rewrite_file_texts(
            connection=connection,
            decrypt_encryption_service=service,
            encrypt_encryption_service=None,
        )
    _retire_blobs(replaced_blob_ids)
    return rewritten_count


def _generate_unique_file_id() -> str:
    for _ in range(_UNIQUE_FILE_ID_ATTEMPTS):
        candidate = str(uuid.uuid4())
        if note_store.has_note(candidate):
            continue
        if file_registry.has_file(candidate):
            continue
        return candidate
    raise RuntimeError("Failed to generate a unique file UUID")


def _derive_thumbnail_kind(*, mime_type: str, original_filename: str) -> str:
    normalized_mime_type = mime_type.strip().lower()
    extension = Path(original_filename).suffix.lower()
    if normalized_mime_type == "application/pdf" or extension == ".pdf":
        return "pdf"
    if normalized_mime_type == EXCALIDRAW_MIME_TYPE or extension == EXCALIDRAW_FILE_EXTENSION:
        return "excalidraw"
    if normalized_mime_type.startswith("image/"):
        return "image"
    if normalized_mime_type.startswith("audio/"):
        return "audio"
    if normalized_mime_type.startswith("video/"):
        return "video"
    if normalized_mime_type.startswith("text/"):
        return "text"
    if extension in {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz"}:
        return "archive"
    return "other"


def _rewrite_file_row(
    *,
    connection,
    row: dict[str, object],
    decrypt_encryption_service: object,
    encrypt_encryption_service: object | None,
) -> str:
    """Rewrite one file's row and blob; returns the old blob, to retire once all is committed."""
    file_id = row["id"]
    if not isinstance(file_id, str) or file_id == "":
        raise TypeError(f"files.id must be a non-empty string, got {file_id!r}")

    title = _decrypt_text_field(
        encryption_service=decrypt_encryption_service,
        value=row["title"],
        nonce=row["title_encryption_nonce"],
        tag=row["title_encryption_tag"],
        field_name="title",
        file_id=file_id,
    )
    metadata_json = _decrypt_text_field(
        encryption_service=decrypt_encryption_service,
        value=row["metadata_json"],
        nonce=row["metadata_encryption_nonce"],
        tag=row["metadata_encryption_tag"],
        field_name="metadata_json",
        file_id=file_id,
    )
    next_blob = _rewritten_blob(
        row=row, file_id=file_id,
        decrypt_encryption_service=decrypt_encryption_service, encrypt_encryption_service=encrypt_encryption_service,
    )

    if encrypt_encryption_service is None:
        next_title = title
        next_title_nonce = None
        next_title_tag = None
        next_metadata_json = metadata_json
        next_metadata_nonce = None
        next_metadata_tag = None
    else:
        next_title, next_title_nonce, next_title_tag = _encrypt_text_for_storage(
            encryption_service=encrypt_encryption_service,
            plaintext=title,
        )
        next_metadata_json, next_metadata_nonce, next_metadata_tag = _encrypt_text_for_storage(
            encryption_service=encrypt_encryption_service,
            plaintext=metadata_json,
        )

    update_file_storage_fields(
        connection,
        file_id=file_id,
        title=next_title,
        title_encryption_nonce=next_title_nonce,
        title_encryption_tag=next_title_tag,
        metadata_json=next_metadata_json,
        metadata_encryption_nonce=next_metadata_nonce,
        metadata_encryption_tag=next_metadata_tag,
        blob_id=next_blob.blob_id,
        blob_seal=next_blob.seal,
        blob_seal_encryption_nonce=next_blob.seal_nonce,
        blob_seal_encryption_tag=next_blob.seal_tag,
        updated_at=datetime.now(timezone.utc),
    )
    return str(row["blob_id"])


def _rewrite_file_previews(
    *,
    connection,
    decrypt_encryption_service: object,
    encrypt_encryption_service: object | None,
) -> list[str]:
    """Rewrite every preview's blob; returns the old blobs, to retire once all is committed."""
    replaced_blob_ids: list[str] = []
    for preview in fetch_all_file_previews(connection):
        file_id = preview["file_id"]
        variant = preview["variant"]
        assert isinstance(file_id, str) and isinstance(variant, str)
        next_blob = _rewritten_blob(
            row=preview, file_id=file_id,
            decrypt_encryption_service=decrypt_encryption_service, encrypt_encryption_service=encrypt_encryption_service,
        )
        update_file_preview_storage_fields(
            connection,
            file_id=file_id,
            variant=variant,
            blob_id=next_blob.blob_id,
            blob_seal=next_blob.seal,
            blob_seal_encryption_nonce=next_blob.seal_nonce,
            blob_seal_encryption_tag=next_blob.seal_tag,
        )
        replaced_blob_ids.append(str(preview["blob_id"]))
    return replaced_blob_ids


def _require_editable(record: FileReferenceRecord) -> None:
    if record.thumbnail_kind not in _EDITABLE_THUMBNAIL_KINDS:
        raise FileNotEditable(f"Files of kind {record.thumbnail_kind!r} cannot be edited in place")


def _decode_utf8_strict(content_bytes: bytes, *, description: str) -> str:
    text = content_bytes.decode("utf-8", errors="replace")
    if text.encode("utf-8") != content_bytes:
        raise InvalidFileContent(f"{description} must be UTF-8 text")
    return text


def _validate_editable_content(*, thumbnail_kind: str, content_bytes: bytes) -> None:
    assert thumbnail_kind in _EDITABLE_THUMBNAIL_KINDS
    text = _decode_utf8_strict(content_bytes, description="Excalidraw scene")
    try:
        scene = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidFileContent("Excalidraw scene must be valid JSON") from exc
    if not isinstance(scene, dict) or "type" not in scene or scene["type"] != "excalidraw":
        raise InvalidFileContent("Excalidraw scene must be a JSON object with type 'excalidraw'")
    if "elements" not in scene or not isinstance(scene["elements"], list):
        raise InvalidFileContent("Excalidraw scene must contain an elements list")


def _validate_svg_preview(*, svg_bytes: bytes, variant: str) -> None:
    if not isinstance(svg_bytes, bytes):
        raise TypeError(f"{variant} preview must be bytes, got {type(svg_bytes)}")
    if len(svg_bytes) > MAX_ATTACHMENT_BYTES:
        raise ValueError("Attachment exceeds the configured size limit")
    text = _decode_utf8_strict(svg_bytes, description=f"{variant} preview").strip()
    if text.startswith("<?xml"):
        if _XML_DECLARATION_END not in text:
            raise InvalidFileContent(f"{variant} preview has an unterminated XML declaration")
        text = text[text.index(_XML_DECLARATION_END) + len(_XML_DECLARATION_END):].lstrip()
    if not text.startswith("<svg") or not text.endswith("</svg>"):
        raise InvalidFileContent(f"{variant} preview must be an SVG document")


def _row_is_fully_plaintext(row: dict[str, object]) -> bool:
    return (
        _field_has_encryption(
            nonce=row["title_encryption_nonce"],
            tag=row["title_encryption_tag"],
            file_id=row["id"],
            field_name="title",
        )
        is False
        and _field_has_encryption(
            nonce=row["metadata_encryption_nonce"],
            tag=row["metadata_encryption_tag"],
            file_id=row["id"],
            field_name="metadata_json",
        )
        is False
        and _field_has_encryption(
            nonce=row["blob_seal_encryption_nonce"],
            tag=row["blob_seal_encryption_tag"],
            file_id=row["id"],
            field_name="blob_seal",
        )
        is False
    )


def _row_is_fully_encrypted(row: dict[str, object]) -> bool:
    return (
        _field_has_encryption(
            nonce=row["title_encryption_nonce"],
            tag=row["title_encryption_tag"],
            file_id=row["id"],
            field_name="title",
        )
        is True
        and _field_has_encryption(
            nonce=row["metadata_encryption_nonce"],
            tag=row["metadata_encryption_tag"],
            file_id=row["id"],
            field_name="metadata_json",
        )
        is True
        and _field_has_encryption(
            nonce=row["blob_seal_encryption_nonce"],
            tag=row["blob_seal_encryption_tag"],
            file_id=row["id"],
            field_name="blob_seal",
        )
        is True
    )


def _field_has_encryption(*, nonce: object, tag: object, file_id: object, field_name: str) -> bool:
    if nonce is None and tag is None:
        return False
    if not isinstance(nonce, bytes) or not isinstance(tag, bytes):
        raise RuntimeError(
            "Encrypted field metadata invalid: "
            f"file_id={file_id} field={field_name} nonce={nonce is not None} tag={tag is not None}"
        )
    return True


def _resolve_encryption_service(token: Optional[str]):
    service = None
    if token is not None and token != "":
        service = get_encryption_service_with_token(token)
    if service is None:
        service = get_encryption_service()
    return service


def _encrypt_text_for_storage(
    *,
    encryption_service: object,
    plaintext: str,
) -> tuple[str, Optional[bytes], Optional[bytes]]:
    if not isinstance(plaintext, str):
        raise TypeError(f"plaintext must be a string, got {type(plaintext)}")

    service = _coerce_encryption_service(encryption_service)
    if service is None:
        if is_encryption_required():
            raise RuntimeError("Encryption is required but no DEK is available")
        return plaintext, None, None
    return service.encrypt_for_storage(plaintext)


def _encrypt_bytes_for_storage(
    *,
    encryption_service: object,
    plaintext: bytes,
) -> tuple[bytes, Optional[bytes], Optional[bytes]]:
    if not isinstance(plaintext, bytes):
        raise TypeError(f"plaintext must be bytes, got {type(plaintext)}")

    service = _coerce_encryption_service(encryption_service)
    if service is None:
        if is_encryption_required():
            raise RuntimeError("Encryption is required but no DEK is available")
        return plaintext, None, None
    return service.encrypt_bytes_for_storage(plaintext)


def _decrypt_text_field(
    *,
    encryption_service,
    value: object,
    nonce: object,
    tag: object,
    field_name: str,
    file_id: str,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"files.{field_name} must be a string for file {file_id}")
    if nonce is None and tag is None:
        return value
    if (nonce is None) != (tag is None):
        raise RuntimeError(
            "Encrypted text metadata missing: "
            f"file_id={file_id} field={field_name} nonce={nonce is not None} tag={tag is not None}"
        )
    if not isinstance(nonce, bytes) or not isinstance(tag, bytes):
        raise RuntimeError(
            "Encrypted text metadata invalid: "
            f"file_id={file_id} field={field_name}"
        )

    service = _coerce_encryption_service(encryption_service)
    if service is None:
        raise RuntimeError(f"Encrypted file metadata requires an active DEK: file_id={file_id}")
    return service.decrypt_from_storage(value, nonce, tag)


def _decrypt_blob_field(
    *,
    encryption_service,
    value: object,
    nonce: object,
    tag: object,
    field_name: str,
    file_id: str,
) -> bytes:
    if not isinstance(value, bytes):
        raise TypeError(f"files.{field_name} must be bytes for file {file_id}")
    if nonce is None and tag is None:
        return value
    if (nonce is None) != (tag is None):
        raise RuntimeError(
            "Encrypted blob metadata missing: "
            f"file_id={file_id} field={field_name} nonce={nonce is not None} tag={tag is not None}"
        )
    if not isinstance(nonce, bytes) or not isinstance(tag, bytes):
        raise RuntimeError(
            "Encrypted blob metadata invalid: "
            f"file_id={file_id} field={field_name}"
        )

    service = _coerce_encryption_service(encryption_service)
    if service is None:
        raise RuntimeError(f"Encrypted file blob requires an active DEK: file_id={file_id}")
    return service.decrypt_bytes_from_storage(value, nonce, tag)


def _write_blob(*, content_bytes: bytes, encryption_service: object) -> _SealedBlob:
    """Store content as a new blob, written and synced: encrypted while the vault has a password."""
    stored = live_blob_store().write(content_bytes, is_encrypted=_coerce_encryption_service(encryption_service) is not None)
    return _sealed_for_catalog(stored=stored, encryption_service=encryption_service)


def _sealed_for_catalog(*, stored: StoredBlob, encryption_service: object) -> _SealedBlob:
    seal, seal_nonce, seal_tag = _encrypt_bytes_for_storage(encryption_service=encryption_service, plaintext=stored.seal.to_bytes())
    return _SealedBlob(blob_id=stored.blob_id, seal=seal, seal_nonce=seal_nonce, seal_tag=seal_tag)


def _open_seal(*, encryption_service: object, row: dict[str, object], file_id: str) -> BlobSeal:
    return BlobSeal.from_bytes(_decrypt_blob_field(
        encryption_service=encryption_service,
        value=row["blob_seal"],
        nonce=row["blob_seal_encryption_nonce"],
        tag=row["blob_seal_encryption_tag"],
        field_name="blob_seal",
        file_id=file_id,
    ))


def _find_and_pin(fetch_row: Callable[..., Optional[dict[str, object]]]) -> Optional[dict[str, object]]:
    """A catalog row and its blob, which cannot be deleted until the caller unpins it."""
    store = live_blob_store()
    with store.lifecycle_lock:
        with connect_file_reader() as connection:
            row = fetch_row(connection)
        if row is not None:
            store.pin([str(row["blob_id"])])
    return row


def _read_pinned_blob(*, encryption_service: object, row: dict[str, object], file_id: str) -> bytes:
    """The whole blob of a row _find_and_pin returned, and the pin released."""
    blob_id = str(row["blob_id"])
    store = live_blob_store()
    try:
        return store.read_all(blob_id, _open_seal(encryption_service=encryption_service, row=row, file_id=file_id))
    finally:
        store.unpin([blob_id])


def _rewritten_blob(
    *, row: dict[str, object], file_id: str, decrypt_encryption_service: object, encrypt_encryption_service: object | None,
) -> _SealedBlob:
    """A row's blob copied, encrypted or not, a piece at a time; the old one stays for retiring."""
    seal = _open_seal(encryption_service=decrypt_encryption_service, row=row, file_id=file_id)
    is_encrypted = _coerce_encryption_service(encrypt_encryption_service) is not None
    copied = live_blob_store().copy(str(row["blob_id"]), seal, is_encrypted=is_encrypted)
    if not is_encrypted:
        # Removing a password: encryption is still required until the change commits.
        return _SealedBlob(blob_id=copied.blob_id, seal=copied.seal.to_bytes(), seal_nonce=None, seal_tag=None)
    return _sealed_for_catalog(stored=copied, encryption_service=encrypt_encryption_service)


def _retire_blobs(blob_ids: list[str]) -> None:
    """Delete blobs the catalog stopped naming, once a password change or restore can't roll back."""
    if blob_ids:
        after_recoverable_commit(lambda: live_blob_store().retire(blob_ids))


def _content_and_preview_blob_ids(connection, file_id: str) -> list[str]:
    blob_ids = fetch_blob_ids_of_files(connection, [file_id])
    for variant in FILE_PREVIEW_VARIANTS:
        preview = fetch_file_preview(connection, file_id, variant)
        if preview is not None:
            blob_ids.append(str(preview["blob_id"]))
    return blob_ids


def _coerce_encryption_service(encryption_service: object):
    if encryption_service is None:
        return None
    if not isinstance(encryption_service.dek, bytes):
        return None
    return encryption_service


def _parse_file_metadata(metadata_json: str, *, file_id: str) -> dict[str, object]:
    metadata = json.loads(metadata_json)
    if not isinstance(metadata, dict):
        raise TypeError(f"files.metadata_json must decode to an object for file {file_id}")

    if "original_filename" not in metadata:
        raise TypeError(f"files.metadata_json original_filename missing for file {file_id}")
    if "mime_type" not in metadata:
        raise TypeError(f"files.metadata_json mime_type missing for file {file_id}")
    if "size_bytes" not in metadata:
        raise TypeError(f"files.metadata_json size_bytes missing for file {file_id}")
    if "thumbnail_kind" not in metadata:
        raise TypeError(f"files.metadata_json thumbnail_kind missing for file {file_id}")

    original_filename = metadata["original_filename"]
    mime_type = metadata["mime_type"]
    size_bytes = metadata["size_bytes"]
    thumbnail_kind = metadata["thumbnail_kind"]

    if not isinstance(original_filename, str) or original_filename == "":
        raise TypeError(f"files.metadata_json original_filename missing for file {file_id}")
    if not isinstance(mime_type, str):
        raise TypeError(f"files.metadata_json mime_type invalid for file {file_id}")
    if not isinstance(size_bytes, int) or size_bytes < 0:
        raise TypeError(f"files.metadata_json size_bytes invalid for file {file_id}")
    if not isinstance(thumbnail_kind, str) or thumbnail_kind not in _ALLOWED_THUMBNAIL_KINDS:
        raise TypeError(f"files.metadata_json thumbnail_kind invalid for file {file_id}")

    return {
        "original_filename": original_filename,
        "mime_type": mime_type,
        "size_bytes": size_bytes,
        "thumbnail_kind": thumbnail_kind,
    }



# --- A file's text for search (file_text_search.py; folder-import-and-file-previews.md) ------


def _stored_payload(
    *, encryption_service: object, row: dict[str, object], field: str, file_id: str,
) -> bytes:
    return _decrypt_blob_field(
        encryption_service=encryption_service,
        value=row[f"{field}_data"],
        nonce=row[f"{field}_encryption_nonce"],
        tag=row[f"{field}_encryption_tag"],
        field_name=f"{field}_data",
        file_id=file_id,
    )


def _integer_column(row: dict[str, object], column: str, *, file_id: str) -> int:
    """An INTEGER column of a stored file text's row, which SQLite returns as an int."""
    value = row[column]
    if not isinstance(value, int):
        raise TypeError(f"file_texts.{column} must be an integer for file {file_id}, got {type(value).__name__}")
    return value


def _read_file_text(file_id: str) -> StoredFileText | None:
    encryption_service = _resolve_encryption_service(None)
    row = _find_and_pin(lambda connection: fetch_file_text(connection, file_id))
    if row is None:
        return None
    text = _read_pinned_blob(encryption_service=encryption_service, row=row, file_id=file_id)
    return StoredFileText(
        text=text.decode("utf-8"), is_cut=bool(row["is_cut"]),
        content_revision=_integer_column(row, "content_revision", file_id=file_id),
        reader_version=_integer_column(row, "reader_version", file_id=file_id),
    )


def _read_file_text_filters() -> list[StoredFilter]:
    encryption_service = _resolve_encryption_service(None)
    with connect_file_reader() as connection:
        rows = fetch_all_file_text_filters(connection)
    return [
        StoredFilter(
            file_id=str(row["file_id"]),
            filter_bytes=_stored_payload(encryption_service=encryption_service, row=row, field="filter", file_id=str(row["file_id"])),
            is_cut=bool(row["is_cut"]),
            content_revision=_integer_column(row, "content_revision", file_id=str(row["file_id"])),
            reader_version=_integer_column(row, "reader_version", file_id=str(row["file_id"])),
            filter_version=_integer_column(row, "filter_version", file_id=str(row["file_id"])),
        )
        for row in rows
    ]


def _registered_file_title(file_id: str) -> str:
    """The name of a file the registry lists (title_of is None only for an id that is no file's)."""
    title = file_registry.title_of(file_id)
    if title is None:
        raise RuntimeError(f"file {file_id} is listed by the file registry but has no title")
    return title


def _searchable_files() -> dict[str, int]:
    file_ids = sorted(
        file_id for file_id in file_registry.file_ids_of_kind(FILE_FILTER_ANY)
        # Its reader goes by its ending (TEXT_READER_VERSIONS): a PDF named without one has none.
        if is_searchable_file_name(_registered_file_title(file_id))
    )
    with connect_file_reader() as connection:
        return fetch_content_revisions(connection, file_ids)


def _store_file_text(file_id: str, kept: KeptText) -> None:
    encryption_service = _resolve_encryption_service(None)
    sealed = _write_blob(content_bytes=kept.extracted.text.encode("utf-8"), encryption_service=encryption_service)
    filter_data, filter_nonce, filter_tag = _encrypt_bytes_for_storage(
        encryption_service=encryption_service, plaintext=kept.filter_bytes,
    )
    with begin_file_writer() as connection:
        file_is_present = fetch_file(connection, file_id) is not None
        replaced_text = fetch_file_text(connection, file_id)
        if file_is_present:
            upsert_file_text(
                connection, file_id=file_id, blob_id=sealed.blob_id, blob_seal=sealed.seal,
                blob_seal_encryption_nonce=sealed.seal_nonce, blob_seal_encryption_tag=sealed.seal_tag,
                filter_data=filter_data, filter_encryption_nonce=filter_nonce,
                filter_encryption_tag=filter_tag, is_cut=kept.extracted.is_cut, content_revision=kept.content_revision,
                reader_version=kept.reader_version, filter_version=kept.filter_version, updated_at=datetime.now(timezone.utc),
            )
    # Deleted meanwhile: nothing to keep.
    if not file_is_present:
        _retire_blobs([sealed.blob_id])
    elif replaced_text is not None:
        _retire_blobs([str(replaced_text["blob_id"])])


def _file_bytes_if_present(file_id: str) -> bytes | None:
    """The file's content, or None when it was deleted (a background read races deletions)."""
    encryption_service = _resolve_encryption_service(None)
    row = _find_and_pin(lambda connection: fetch_file(connection, file_id))
    if row is None:
        return None
    return _read_pinned_blob(encryption_service=encryption_service, row=row, file_id=file_id)


file_texts.install_storage(FileTextStorage(
    read_text=_read_file_text,
    read_filters=_read_file_text_filters,
    searchable_files=_searchable_files,
    read_file_bytes=_file_bytes_if_present,
    file_name=file_registry.title_of,
    store_text=_store_file_text,
))


def _rewrite_file_texts(
    *,
    connection,
    decrypt_encryption_service: object,
    encrypt_encryption_service: object | None,
) -> list[str]:
    """Rewrite every file text's blob and filter; returns the old blobs, to retire once all is committed."""
    replaced_blob_ids: list[str] = []
    for row in fetch_all_file_texts(connection):
        file_id = str(row["file_id"])
        next_blob = _rewritten_blob(
            row=row, file_id=file_id,
            decrypt_encryption_service=decrypt_encryption_service, encrypt_encryption_service=encrypt_encryption_service,
        )
        filter_data, filter_nonce, filter_tag = _rewritten_payload(
            row=row, field="filter", file_id=file_id,
            decrypt_encryption_service=decrypt_encryption_service, encrypt_encryption_service=encrypt_encryption_service,
        )
        update_file_text_storage_fields(
            connection, file_id=file_id, blob_id=next_blob.blob_id, blob_seal=next_blob.seal,
            blob_seal_encryption_nonce=next_blob.seal_nonce, blob_seal_encryption_tag=next_blob.seal_tag,
            filter_data=filter_data, filter_encryption_nonce=filter_nonce, filter_encryption_tag=filter_tag,
        )
        replaced_blob_ids.append(str(row["blob_id"]))
    return replaced_blob_ids


def _rewritten_payload(
    *, row: dict[str, object], field: str, file_id: str,
    decrypt_encryption_service: object, encrypt_encryption_service: object | None,
) -> tuple[bytes, Optional[bytes], Optional[bytes]]:
    """One payload of a file text decrypted, then encrypted again (or left plain without a key)."""
    plaintext = _stored_payload(encryption_service=decrypt_encryption_service, row=row, field=field, file_id=file_id)
    if encrypt_encryption_service is None:
        return plaintext, None, None
    return _encrypt_bytes_for_storage(encryption_service=encrypt_encryption_service, plaintext=plaintext)
