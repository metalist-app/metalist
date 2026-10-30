from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from app.db.file_session import resolve_file_database_path
from app.db.file_session import connect_file_reader
from app.db.files_sql import fetch_file
from app.models.database import SafeSession
from app.security.encryption import clear_encryption_key, set_encryption_required, set_session_dek
from app.services.file_registry import file_registry, referenced_file_ids
from app.services.file_storage import create_file, download_file, trim_unused_files


def test_resolve_file_database_path_uses_sibling_files_name() -> None:
    path = resolve_file_database_path(Path("/tmp/namespaces/default/default.metalist.db"))
    assert path == Path("/tmp/namespaces/default/default.metalist.files.db")


def test_resolve_file_database_path_supports_namespaced_database_name() -> None:
    path = resolve_file_database_path(Path("/tmp/work/work.metalist.db"))
    assert path == Path("/tmp/work/work.metalist.files.db")


def test_create_file_encrypts_at_rest_and_download_round_trips(tmp_path: Path, monkeypatch) -> None:
    set_encryption_required(True)
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    set_session_dek(os.urandom(32))
    file_registry.reset()
    try:
        record = create_file(
            original_filename="report.pdf",
            mime_type="application/pdf",
            content_bytes=b"hello encrypted world",
            token="token",
        )

        assert file_registry.has_file(record.id) is True

        with connect_file_reader() as connection:
            row = fetch_file(connection, record.id)
        assert row is not None
        assert row["title"] != "report.pdf"
        assert b"hello encrypted world" != row["blob_data"]

        downloaded = download_file(record.id, "token")
        assert downloaded.record.title == "report.pdf"
        assert downloaded.record.original_filename == "report.pdf"
        assert downloaded.record.mime_type == "application/pdf"
        assert downloaded.record.thumbnail_kind == "pdf"
        assert downloaded.content_bytes == b"hello encrypted world"
    finally:
        file_registry.reset()
        clear_encryption_key()
        set_encryption_required(False)
        SafeSession.use_file_db()


def test_create_file_without_password_stores_plaintext_and_downloads(tmp_path: Path, monkeypatch) -> None:
    set_encryption_required(False)
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    file_registry.reset()
    try:
        record = create_file(
            original_filename="plain.txt",
            mime_type="text/plain",
            content_bytes=b"hello plaintext world",
            token="token",
        )

        assert file_registry.has_file(record.id) is True

        with connect_file_reader() as connection:
            row = fetch_file(connection, record.id)
        assert row is not None
        assert row["title"] == "plain.txt"
        assert row["title_encryption_nonce"] is None
        assert row["title_encryption_tag"] is None
        assert row["blob_data"] == b"hello plaintext world"
        assert row["blob_encryption_nonce"] is None
        assert row["blob_encryption_tag"] is None

        downloaded = download_file(record.id, "token")
        assert downloaded.record.title == "plain.txt"
        assert downloaded.record.original_filename == "plain.txt"
        assert downloaded.record.mime_type == "text/plain"
        assert downloaded.record.thumbnail_kind == "text"
        assert downloaded.content_bytes == b"hello plaintext world"
    finally:
        file_registry.reset()
        clear_encryption_key()
        set_encryption_required(False)
        SafeSession.use_file_db()


@dataclass(frozen=True)
class _FakeNote:
    content: str


class _FakeNoteStore:
    loaded = True

    def __init__(self, notes: dict[str, _FakeNote]) -> None:
        self._notes = notes

    def list_note_ids(self) -> list[str]:
        return list(self._notes.keys())

    def get_note(self, note_id: str) -> _FakeNote:
        return self._notes[note_id]

    def referenced_target_ids(self) -> frozenset[str]:
        return frozenset(file_id for note in self._notes.values() for file_id in referenced_file_ids(note.content))


def test_trim_unused_files_deletes_only_unreferenced_rows(tmp_path: Path, monkeypatch) -> None:
    set_encryption_required(True)
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    set_session_dek(os.urandom(32))
    file_registry.reset()
    try:
        kept = create_file(
            original_filename="kept.pdf",
            mime_type="application/pdf",
            content_bytes=b"keep me",
            token="token",
        )
        deleted = create_file(
            original_filename="deleted.txt",
            mime_type="text/plain",
            content_bytes=b"delete me",
            token="token",
        )

        fake_store = _FakeNoteStore(
            notes={
                "note-1": _FakeNote(content=f"<div>![[{kept.id}]]</div>"),
            }
        )
        monkeypatch.setattr("app.services.file_storage.note_store", fake_store)

        result = trim_unused_files(kept_file_ids=frozenset())
        assert result.deleted_count == 1
        assert result.deleted_file_ids == [deleted.id]
        assert file_registry.has_file(kept.id) is True
        assert file_registry.has_file(deleted.id) is False
    finally:
        file_registry.reset()
        clear_encryption_key()
        set_encryption_required(False)
        SafeSession.use_file_db()
