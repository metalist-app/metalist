"""Rename File… (docs/ui/references.md, Renaming files): a file's new name is what its
cards show, what search finds and what it downloads as; nothing else about it changes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import app.services.file_storage as file_storage_module
import app.services.note_store as note_store_module
from app.db.file_schema import FILE_PREVIEWS_TABLE
from app.db.file_session import begin_file_writer, connect_file_reader
from app.db.files_sql import fetch_file
from app.models.database import SafeSession
from app.security.encryption import clear_encryption_key, set_encryption_required, set_session_dek
from app.services.backup_service import create_timestamped_backup_for_paths, restore_backup_to_paths
from app.services.file_registry import file_registry
from app.services.file_storage import bootstrap_file_registry, create_file, download_file, rename_file
from app.services.input_errors import InputRejected
from app.services.note_store import NoteStore
from app.services.search_index import SearchIndex
from app.services.tag_ontology import TagOntology

SCENE = json.dumps({"type": "excalidraw", "version": 2, "elements": [], "appState": {}, "files": {}}).encode()
LEASE_NOTE = "11111111-1111-4111-8111-111111111111"
FOLDER_NOTE = "22222222-2222-4222-8222-222222222222"
OTHER_NOTE = "33333333-3333-4333-8333-333333333333"


def _clear_shared_memory_file_database() -> None:
    # The in-memory file database is shared for the whole test process; start each test empty.
    with begin_file_writer() as connection:
        connection.execute("DELETE FROM files")
        assert connection.execute(f"SELECT count(*) FROM {FILE_PREVIEWS_TABLE}").fetchone()[0] == 0


class _RecordingNoteStore:
    """Notes referencing files, as the backlink index knows them; records search refreshes."""

    def __init__(self, referrers_by_file_id: dict[str, set[str]]) -> None:
        self._referrers_by_file_id = referrers_by_file_id
        self.refreshed: list[set[str]] = []

    def has_note(self, note_id: str) -> bool:
        return False

    def note_ids_referencing(self, target_ids: set[str]) -> set[str]:
        return set().union(*(self._referrers_by_file_id.get(file_id, set()) for file_id in target_ids))

    def refresh_search_text_for_notes(self, note_ids: set[str]) -> None:
        self.refreshed.append(set(note_ids))


@pytest.fixture
def encrypted_files(tmp_path: Path, monkeypatch):
    set_encryption_required(True)
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    set_session_dek(os.urandom(32))
    file_registry.reset()
    _clear_shared_memory_file_database()
    yield
    file_registry.reset()
    clear_encryption_key()
    set_encryption_required(False)
    SafeSession.use_file_db()


@pytest.fixture
def notes(monkeypatch) -> _RecordingNoteStore:
    store = _RecordingNoteStore({})
    monkeypatch.setattr(file_storage_module, "note_store", store)
    return store


def _create_pdf() -> str:
    return create_file(
        original_filename="scan_0042.pdf", mime_type="application/pdf", content_bytes=b"%PDF lease", token="token",
    ).id


def test_renaming_changes_the_shown_and_downloaded_name_and_nothing_else(encrypted_files, notes) -> None:
    file_id = _create_pdf()
    before = download_file(file_id, "token").record

    renamed = rename_file(file_id=file_id, name="Lease 2026.pdf", token="token")

    assert renamed.title == "Lease 2026.pdf"
    assert renamed.original_filename == "Lease 2026.pdf"
    downloaded = download_file(file_id, "token")
    assert downloaded.record.title == "Lease 2026.pdf"
    assert downloaded.record.original_filename == "Lease 2026.pdf"
    assert downloaded.content_bytes == b"%PDF lease"
    assert (downloaded.record.mime_type, downloaded.record.size_bytes, downloaded.record.thumbnail_kind) == (
        before.mime_type, before.size_bytes, before.thumbnail_kind)
    assert downloaded.record.content_revision == before.content_revision
    assert file_registry.title_of(file_id) == "Lease 2026.pdf"
    # Both names stay encrypted at rest.
    with connect_file_reader() as connection:
        row = fetch_file(connection, file_id)
    assert row is not None
    assert row["title_encryption_nonce"] is not None and "Lease" not in row["title"]
    assert row["metadata_encryption_nonce"] is not None and "Lease" not in row["metadata_json"]


def test_renaming_refreshes_search_for_the_notes_showing_the_file_and_rerenders_views(encrypted_files, notes) -> None:
    file_id = _create_pdf()
    other_id = _create_pdf()
    notes._referrers_by_file_id.update({file_id: {LEASE_NOTE, FOLDER_NOTE}, other_id: {OTHER_NOTE}})
    generation = file_registry.names_generation()

    rename_file(file_id=file_id, name="Lease 2026.pdf", token="token")

    assert notes.refreshed == [{LEASE_NOTE, FOLDER_NOTE}]
    assert file_registry.names_generation() == generation + 1


@pytest.mark.parametrize(("typed", "expected"), [
    ("a/b:c.pdf", "a-b-c.pdf"),
    ('q*u?o"t<e>|s.pdf', "q-u-o-t-e--s.pdf"),
    ("  padded name  .pdf", "padded name.pdf"),
    ("tab\there.pdf", "tab-here.pdf"),
    ("/.pdf", "-.pdf"),
])
def test_characters_a_file_name_cannot_hold_become_dashes(encrypted_files, notes, typed: str, expected: str) -> None:
    file_id = _create_pdf()
    assert rename_file(file_id=file_id, name=typed, token="token").title == expected


@pytest.mark.parametrize(("typed", "message"), [
    ("scan_0042.txt", "A file's extension can't change: keep .pdf."),
    ("scan_0042", "A file's extension can't change: keep .pdf."),
    (".pdf", "A file's extension can't change: keep .pdf."),
    ("  .pdf", "A file's extension can't change: keep .pdf."),
    (" . .pdf", "A file name can't be blank."),
    (f"{'x' * 252}.pdf", "A file name can be at most 255 characters long."),
])
def test_a_changed_extension_a_blank_or_an_overlong_name_is_refused(encrypted_files, notes, typed: str, message: str) -> None:
    file_id = _create_pdf()
    with pytest.raises(InputRejected) as refused:
        rename_file(file_id=file_id, name=typed, token="token")
    assert str(refused.value) == message
    assert download_file(file_id, "token").record.title == "scan_0042.pdf"
    assert notes.refreshed == []


def test_the_longest_name_allowed_is_kept(encrypted_files, notes) -> None:
    file_id = _create_pdf()
    longest = f"{'x' * 251}.pdf"
    assert rename_file(file_id=file_id, name=longest, token="token").title == longest


def test_a_file_without_an_extension_is_renamed_whole_and_cannot_gain_one(encrypted_files, notes) -> None:
    file_id = create_file(original_filename="Makefile", mime_type="text/plain", content_bytes=b"all:", token="token").id
    assert rename_file(file_id=file_id, name="Build rules", token="token").title == "Build rules"
    with pytest.raises(InputRejected) as refused:
        rename_file(file_id=file_id, name="Build.rules", token="token")
    assert str(refused.value) == "A file's extension can't change: keep no extension."


def test_the_same_name_changes_nothing(encrypted_files, notes) -> None:
    file_id = _create_pdf()
    generation = file_registry.names_generation()
    with connect_file_reader() as connection:
        updated_at = fetch_file(connection, file_id)["updated_at"]

    assert rename_file(file_id=file_id, name="scan_0042.pdf", token="token").title == "scan_0042.pdf"

    assert file_registry.names_generation() == generation
    assert notes.refreshed == []
    with connect_file_reader() as connection:
        assert fetch_file(connection, file_id)["updated_at"] == updated_at


def test_a_diagram_keeps_its_kind_revision_and_content(encrypted_files, notes) -> None:
    record = create_file(
        original_filename="Diagram.excalidraw", mime_type="application/vnd.excalidraw+json",
        content_bytes=SCENE, token="token",
    )
    renamed = rename_file(file_id=record.id, name="Kitchen plan.excalidraw", token="token")
    assert renamed.title == "Kitchen plan.excalidraw"
    assert renamed.thumbnail_kind == "excalidraw"
    assert renamed.content_revision == record.content_revision
    assert download_file(record.id, "token").content_bytes == SCENE


def test_search_finds_notes_by_the_new_name_only(encrypted_files, monkeypatch) -> None:
    file_id = _create_pdf()
    contents = {
        LEASE_NOTE: f"<div>Signed ![[{file_id}]]</div>",
        FOLDER_NOTE: f"<div>Folder [[{file_id}]]</div>",
        OTHER_NOTE: "<div>scan_0042 typed in a note</div>",
    }
    rows = [
        dict(id=LEASE_NOTE, parent_id=None, prev_id=None, next_id=FOLDER_NOTE, is_collapsed=False, created_at=None, updated_at=None),
        dict(id=FOLDER_NOTE, parent_id=None, prev_id=LEASE_NOTE, next_id=OTHER_NOTE, is_collapsed=False, created_at=None, updated_at=None),
        dict(id=OTHER_NOTE, parent_id=None, prev_id=FOLDER_NOTE, next_id=None, is_collapsed=False, created_at=None, updated_at=None),
    ]
    index = SearchIndex()
    monkeypatch.setattr(note_store_module, "search_index", index)
    monkeypatch.setattr(note_store_module, "get_cached_content", contents.__getitem__)
    monkeypatch.setattr(note_store_module, "get_cached_text", contents.__getitem__)
    monkeypatch.setattr(note_store_module, "get_cached_tags", lambda _: "")
    monkeypatch.setattr(note_store_module, "get_cached_proposed_tags", lambda _: "")
    monkeypatch.setattr(note_store_module, "get_ontology", TagOntology.empty)
    store = NoteStore()
    store._timing_enabled = False
    store.load_from_db(None, prefetched_rows=rows)
    monkeypatch.setattr(file_storage_module, "note_store", store)
    assert index.query_note_ids('"scan_0042"') == {LEASE_NOTE, FOLDER_NOTE, OTHER_NOTE}
    revision = index.revision

    rename_file(file_id=file_id, name="Lease 2026.pdf", token="token")

    assert index.query_note_ids('"lease 2026"') == {LEASE_NOTE, FOLDER_NOTE}
    assert index.query_note_ids('"scan_0042"') == {OTHER_NOTE}
    assert index.revision > revision


def test_the_new_name_survives_locking_and_unlocking(encrypted_files, notes) -> None:
    dek = os.urandom(32)
    set_session_dek(dek)
    file_id = _create_pdf()
    rename_file(file_id=file_id, name="Lease 2026.pdf", token="token")

    # Locking forgets the key and every file's name; unlocking reads them back.
    clear_encryption_key()
    file_registry.reset()
    set_session_dek(dek)
    bootstrap_file_registry()

    assert file_registry.title_of(file_id) == "Lease 2026.pdf"
    assert download_file(file_id, "token").record.original_filename == "Lease 2026.pdf"


def test_a_backup_holds_the_name_it_was_taken_with(tmp_path: Path, monkeypatch, notes) -> None:
    set_encryption_required(True)
    database_path = tmp_path / "vault.metalist.db"
    monkeypatch.setattr(SafeSession, "_db_path", database_path)
    SafeSession.use_file_db()
    dek = os.urandom(32)
    set_session_dek(dek)
    file_registry.reset()
    try:
        SafeSession().close()
        file_id = _create_pdf()
        rename_file(file_id=file_id, name="Lease 2026.pdf", token="token")
        backup_directory = tmp_path / "backups"
        backup = create_timestamped_backup_for_paths(database_path, backup_directory)
        rename_file(file_id=file_id, name="Lease draft.pdf", token="token")

        restore_backup_to_paths(backup_directory / backup.filename, database_path)
        file_registry.reset()
        bootstrap_file_registry()

        assert file_registry.title_of(file_id) == "Lease 2026.pdf"
        assert download_file(file_id, "token").record.original_filename == "Lease 2026.pdf"
    finally:
        file_registry.reset()
        clear_encryption_key()
        set_encryption_required(False)
        SafeSession.use_file_db()


def test_http_routes_read_and_rename_a_file(tmp_path: Path) -> None:
    script = '''
from fastapi.testclient import TestClient
from app.main import app
from app.config import API_PREFIX
from app.services.tokens import token_service

token = token_service.create_token(client_info="fixture", owner_tab_id="tab", dek=None)
headers = {"Authorization": "Bearer " + token, "X-Metalist-Tab-Id": "tab", "Origin": "http://localhost"}
with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as client:
    created = client.post(API_PREFIX + "/files/upload", headers=headers,
                          files={"file": ("scan_0042.pdf", b"%PDF lease", "application/pdf")})
    assert created.status_code == 200, created.text
    file_id = created.json()["file_id"]
    name_path = API_PREFIX + f"/files/{file_id}/name"

    assert client.get(name_path, headers=headers).json() == {"file_id": file_id, "name": "scan_0042.pdf"}
    renamed = client.put(name_path, headers=headers, json={"name": "a/b:c.pdf"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json() == {"file_id": file_id, "name": "a-b-c.pdf"}
    assert client.get(name_path, headers=headers).json()["name"] == "a-b-c.pdf"
    download = client.get(API_PREFIX + f"/files/{file_id}/download", headers=headers)
    assert "a-b-c.pdf" in download.headers["content-disposition"], download.headers["content-disposition"]

    refused = client.put(name_path, headers=headers, json={"name": "a-b-c.txt"})
    assert refused.status_code == 400, refused.text
    assert refused.json() == {"detail": "A file's extension can't change: keep .pdf.", "inputRejected": True}
    blank = client.put(name_path, headers=headers, json={"name": ""})
    assert blank.status_code == 422, (blank.status_code, blank.text)
    unknown = client.put(API_PREFIX + "/files/00000000-0000-4000-8000-000000000000/name", headers=headers, json={"name": "x.pdf"})
    assert unknown.status_code == 404, unknown.text
    unauthenticated = client.put(name_path, headers={"Origin": "http://localhost"}, json={"name": "x.pdf"})
    assert unauthenticated.status_code == 401, unauthenticated.text
print("ROUTES OK")
'''
    environment = dict(os.environ, METALIST_DATA_DIRECTORY=str(tmp_path), METALIST_ENVIRONMENT="production")
    result = subprocess.run([sys.executable, "-c", script], env=environment, capture_output=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, (result.stdout[-2000:], result.stderr[-3000:])
    assert "ROUTES OK" in result.stdout
