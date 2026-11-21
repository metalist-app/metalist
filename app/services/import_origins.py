"""Where each import's notes came from (docs/ready-to-build/import-export-launch.md §5, "Importing again"): a row per import
in the vault, encrypted like the notes while the vault has a password, naming each file's path
in its folder, a fingerprint of the file as it was, its root note, and a fingerprint of its
notes as written. Importing the folder again reads them to tell which files came in before,
which changed since, and which of their notes were edited in MetaList."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Dict

from app.db.import_origins_sql import fetch_all_import_origins, insert_import_origins, update_import_origins_state
from app.db.session import begin_writer
from app.security.encryption import get_encryption_service, is_encryption_required
from app.services.content_cache import get_cached_content, get_cached_tags
from app.services.encryption import EncryptionService
from app.services.store import store

# Between a note's text, its tags and the next note in a fingerprint: in none of them.
_FIELD_END = b"\x00"
_NOTE_END = b"\x01"


@dataclass(frozen=True)
class ImportedFile:
    """One file of an import, as recorded."""

    path: str
    fingerprint: str
    root_id: str
    # Its notes as written: the same now means nobody edited them.
    written: str


@dataclass(frozen=True)
class EarlierFile:
    """A file as its latest import recorded it, its root note still in the vault."""

    file: ImportedFile
    imported_at: datetime


def text_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pieces_fingerprint(pieces: Iterable[bytes]) -> str:
    digest = hashlib.sha256()
    for piece in pieces:
        digest.update(piece)
    return digest.hexdigest()


class FingerprintedPieces:
    """A file's pieces passed on as they are read, fingerprinted on the way: its fingerprint
    once all were read."""

    def __init__(self, pieces: Iterable[bytes]) -> None:
        self._pieces = pieces
        self._digest = hashlib.sha256()
        self._is_read = False

    def __iter__(self) -> Iterator[bytes]:
        for piece in self._pieces:
            self._digest.update(piece)
            yield piece
        self._is_read = True

    def fingerprint(self) -> str:
        assert self._is_read, "a file's fingerprint is asked once all of it was read"
        return self._digest.hexdigest()


def notes_fingerprint(root_id: str) -> str:
    """The note and everything under it, as the vault holds them now: each note's text and
    tags, in order. Folding and moving the root change nothing in it."""
    digest = hashlib.sha256()
    waiting = [root_id]
    while waiting:
        note_id = waiting.pop()
        digest.update(get_cached_content(note_id).encode("utf-8"))
        digest.update(_FIELD_END)
        digest.update(get_cached_tags(note_id).encode("utf-8"))
        digest.update(_NOTE_END)
        waiting.extend(reversed(store.children(note_id)))
    return digest.hexdigest()


def _folder_key(folder_name: str, prefix_folder: str) -> tuple[str, str]:
    """What makes two imports the same folder coming into the same place."""
    return folder_name.casefold(), prefix_folder.casefold()


def record_import(*, folder_name: str, prefix_folder: str, imported_at: datetime, files: Sequence[ImportedFile]) -> None:
    """Keep where this import's notes came from."""
    assert files, "an import records the files it wrote"
    state_json = json.dumps({
        "folderName": folder_name, "prefixFolder": prefix_folder, "importedAt": imported_at.isoformat(),
        "files": [[imported.path, imported.fingerprint, imported.root_id, imported.written] for imported in files],
    }, separators=(",", ":"))
    stored_json, nonce, tag = _for_storage(state_json, encryption_service=get_encryption_service())
    with begin_writer() as connection:
        insert_import_origins(
            connection, state_json=stored_json, state_encryption_nonce=nonce, state_encryption_tag=tag,
            created_at=imported_at,
        )


def earlier_files(*, folder_name: str, prefix_folder: str) -> Dict[str, EarlierFile]:
    """Each file that folder brought into that place before, by its path: as its latest import
    recorded it, left out once its root note is gone (deleted since, or replaced)."""
    wanted = _folder_key(folder_name, prefix_folder)
    found: Dict[str, EarlierFile] = {}
    with begin_writer() as connection:
        rows = fetch_all_import_origins(connection)
    service = get_encryption_service()
    for row in rows:
        state = json.loads(_from_storage(row.state_json, row.state_encryption_nonce, row.state_encryption_tag, service))
        if _folder_key(state["folderName"], state["prefixFolder"]) != wanted:
            continue
        imported_at = datetime.fromisoformat(state["importedAt"])
        for path, fingerprint, root_id, written in state["files"]:
            if store.contains(root_id):
                # Rows come oldest first: a later import's record replaces an earlier one's.
                found[path] = EarlierFile(
                    file=ImportedFile(path=path, fingerprint=fingerprint, root_id=root_id, written=written),
                    imported_at=imported_at,
                )
    return found


def rewrite_persisted_import_origins(*, connection: object, encryption_service: EncryptionService | None, force_plaintext: bool) -> int:
    """Encrypt (a password added) or decrypt (removed) every import's record; how many changed."""
    should_be_encrypted = not force_plaintext
    target_service = None
    if should_be_encrypted:
        target_service = encryption_service
        assert target_service is not None, "encrypting the import records needs the vault's key"
    rewritten_count = 0
    for row in fetch_all_import_origins(connection):
        if (row.state_encryption_nonce is not None) == should_be_encrypted:
            continue
        state_json = _from_storage(row.state_json, row.state_encryption_nonce, row.state_encryption_tag, encryption_service)
        stored_json: str = state_json
        nonce: bytes | None = None
        tag: bytes | None = None
        if target_service is not None:
            stored_json, nonce, tag = target_service.encrypt_for_storage(state_json)
        update_import_origins_state(
            connection, row_id=row.id, state_json=stored_json, state_encryption_nonce=nonce, state_encryption_tag=tag,
        )
        rewritten_count += 1
    return rewritten_count


def _for_storage(state_json: str, *, encryption_service: EncryptionService | None) -> tuple[str, bytes | None, bytes | None]:
    if encryption_service is not None:
        return encryption_service.encrypt_for_storage(state_json)
    if is_encryption_required():
        raise RuntimeError("Saving where an import came from requires the vault's key")
    return state_json, None, None


def _from_storage(
    state_json: str, nonce: bytes | None, tag: bytes | None, encryption_service: EncryptionService | None,
) -> str:
    if nonce is None:
        return state_json
    if encryption_service is None or tag is None:
        raise RuntimeError("An import's record is encrypted and the vault's key is not at hand")
    plaintext = encryption_service.decrypt_from_storage(state_json, nonce, tag)
    if not isinstance(plaintext, str):
        raise TypeError("a decrypted import record must be a string")
    return plaintext
