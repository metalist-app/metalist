"""A folder dropped on the page, uploaded file by file into a holding folder outside the vault
(docs/ready-to-build/desktop-drops-into-folders.md §4): the checklist comes from the
browser's list of its files before anything is sent, and only the ticked files are sent."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import subprocess
import sys

import pytest

from app.services import import_uploads
from app.services.input_errors import InputRejected
from app.services.obsidian_import.file_groups import file_groups, folder_files
from app.services.obsidian_import.import_folder import DiskFolder
from app.services.obsidian_import.vault import count_markdown_files, read_vault


@pytest.fixture(autouse=True)
def data_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("METALIST_DATA_DIRECTORY", str(tmp_path / "data"))
    return tmp_path / "data"


# When the files of these tests were last changed on the computer they were dropped from.
CHANGED_AT = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)
CHANGED_AT_MS = "1792054800000"


def _store(upload_id: str, path: str, content: bytes) -> None:
    with import_uploads.receive_file(upload_id) as incoming:
        incoming.open(path, CHANGED_AT).write(content)


# A dropped file took the time it was uploaded as both its dates (found 2026-11-20): its notes
# were dated the day of the import, and "Changed since" could not tell old files from new.
def test_a_dropped_file_keeps_the_date_it_was_last_changed() -> None:
    upload_id, folder_path = import_uploads.start_upload()
    _store(upload_id, "notes/plan.md", b"# Plan\n")

    held = import_uploads.open_import_folder(Path(folder_path))

    assert held.file_times(PurePosixPath("notes/plan.md")) == (CHANGED_AT, CHANGED_AT)


def test_the_browsers_milliseconds_are_read_as_a_moment() -> None:
    assert CHANGED_AT.timestamp() * 1000 == int(CHANGED_AT_MS)
    assert import_uploads.modified_moment(CHANGED_AT_MS) == CHANGED_AT
    # A file dated before 1970.
    assert import_uploads.modified_moment("-86400000") == datetime(1969, 12, 31, tzinfo=timezone.utc)


@pytest.mark.parametrize("sent", ["", "yesterday", "17920548e5", "1792054800000.5", "9" * 20, "-" + "9" * 20])
def test_a_date_that_is_no_number_of_milliseconds_is_refused(sent: str) -> None:
    with pytest.raises(InputRejected):
        import_uploads.modified_moment(sent)


def test_the_checklist_from_a_list_of_files_is_the_one_a_folder_on_disk_gives(tmp_path: Path) -> None:
    folder = tmp_path / "Photos"
    files = {"beach.jpg": b"j" * 300, "notes/plan.md": b"# Plan\n", ".DS_Store": b"x", "node_modules/a/index.js": b"js"}
    for relative, content in files.items():
        (folder / relative).parent.mkdir(parents=True, exist_ok=True)
        (folder / relative).write_bytes(content)
    listed = import_uploads.listed_files([[relative, len(content)] for relative, content in files.items()])
    assert file_groups(listed) == file_groups(folder_files(DiskFolder(folder)))


@pytest.mark.parametrize("path", ["", "/etc/passwd", "../outside.txt", "notes/../../outside.txt", "notes//a.md", "./a.md", "a\\b.md", "C:/a.md"])
def test_a_path_that_could_leave_the_holding_folder_is_refused(path: str) -> None:
    with pytest.raises(InputRejected):
        import_uploads.relative_path(path)


def test_uploaded_files_land_in_their_own_holding_folder_and_leave_with_it(data_directory: Path) -> None:
    upload_id, folder_path = import_uploads.start_upload()
    folder = Path(folder_path)
    assert folder.is_dir() and folder.is_absolute()
    assert data_directory in folder.parents
    _store(upload_id, "notes/plan.md", b"# Plan\n")
    _store(upload_id, "beach.jpg", b"jpeg")
    held = import_uploads.open_import_folder(folder)
    assert held.read_bytes(PurePosixPath("notes/plan.md")) == b"# Plan\n"
    assert [str(found.path) for found in folder_files(held)] == ["beach.jpg", "notes/plan.md"]
    with pytest.raises(InputRejected, match="already"):
        _store(upload_id, "beach.jpg", b"again")
    import_uploads.discard_upload(upload_id)
    assert not folder.exists()


def test_a_held_file_shows_neither_its_content_nor_its_name_on_disk(data_directory: Path) -> None:
    upload_id, folder_path = import_uploads.start_upload()
    _store(upload_id, "taxes/return-2024.pdf", b"My income was this much")

    on_disk = [path for path in Path(folder_path).rglob("*") if path.is_file()]

    assert len(on_disk) == 1
    assert "return" not in str(on_disk[0]) and "taxes" not in str(on_disk[0])
    stored = on_disk[0].read_bytes()
    assert stored.startswith(b"ML\x01\x01") and b"income" not in stored


def test_a_held_folder_walks_like_one_on_disk(tmp_path: Path) -> None:
    files = {"a.md": b"a", "notes/b.md": b"bb", "notes/deep/c.png": b"ccc", ".hidden/d.txt": b"d"}
    on_disk = tmp_path / "on-disk"
    for relative, content in files.items():
        (on_disk / relative).parent.mkdir(parents=True, exist_ok=True)
        (on_disk / relative).write_bytes(content)
    upload_id, folder_path = import_uploads.start_upload()
    for relative, content in files.items():
        _store(upload_id, relative, content)
    held = import_uploads.open_import_folder(Path(folder_path))

    assert folder_files(held) == folder_files(DiskFolder(on_disk))
    assert count_markdown_files(held) == count_markdown_files(DiskFolder(on_disk))
    assert b"".join(held.pieces(PurePosixPath("notes/deep/c.png"))) == b"ccc"


def test_a_hidden_folder_is_not_gone_into_when_held(tmp_path: Path) -> None:
    upload_id, folder_path = import_uploads.start_upload()
    _store(upload_id, ".git/config", b"x")
    _store(upload_id, "note.md", b"# Note")

    vault = read_vault(import_uploads.open_import_folder(Path(folder_path)), reads_line_break_setting=True)

    assert [str(file.path) for file in vault.markdown_files] == ["note.md"]
    assert [entry.path for entry in vault.skipped] == [".git/"]


def test_a_large_held_file_reads_back_a_piece_at_a_time(data_directory: Path) -> None:
    upload_id, folder_path = import_uploads.start_upload()
    _store(upload_id, "big.bin", b"x" * 300_000)
    held = import_uploads.open_import_folder(Path(folder_path))

    assert held.size(PurePosixPath("big.bin")) == 300_000
    assert b"".join(held.pieces(PurePosixPath("big.bin"))) == b"x" * 300_000


def test_a_lock_ends_every_upload_and_its_keys(data_directory: Path) -> None:
    upload_id, folder_path = import_uploads.start_upload()
    _store(upload_id, "a.md", b"a")

    import_uploads.discard_every_upload()

    assert not Path(folder_path).exists()
    with pytest.raises(InputRejected, match="gone"):
        _store(upload_id, "b.md", b"b")


def test_a_path_sent_twice_at_once_is_refused_when_it_finishes(data_directory: Path) -> None:
    upload_id, _folder_path = import_uploads.start_upload()

    with pytest.raises(InputRejected, match="already"):
        with import_uploads.receive_file(upload_id) as first:
            first.open("a.md", CHANGED_AT).write(b"one")
            _store(upload_id, "a.md", b"two")


def test_an_unknown_upload_is_refused() -> None:
    with pytest.raises(InputRejected):
        _store("not-an-upload", "a.md", b"a")
    with pytest.raises(InputRejected):
        _store("0b6f4c4e-0f43-4a8e-9a2a-2c7f3c1b8e11", "a.md", b"a")


def test_holding_folders_left_from_before_a_restart_are_discarded() -> None:
    upload_id, folder_path = import_uploads.start_upload()
    _store(upload_id, "a.md", b"a")
    import_uploads.discard_every_upload()
    assert not Path(folder_path).exists()
    import_uploads.discard_every_upload()


def test_listed_paths_are_checked_too() -> None:
    assert import_uploads.listed_files([["a/b.md", 3]])[0].path == PurePosixPath("a/b.md")
    with pytest.raises(InputRejected):
        import_uploads.listed_files([["../x.md", 3]])
    with pytest.raises(InputRejected):
        import_uploads.listed_files([["x.md", -1]])


def test_a_dropped_folder_goes_through_the_routes_list_upload_import_ready_and_discard(tmp_path: Path) -> None:
    # The real application in its own process (importing app.main opens a vault in the data directory).
    script = '''
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.services.tokens import token_service
from app.config import API_PREFIX
client = TestClient(app, base_url="http://localhost")
token = token_service.create_token(client_info="fixture", dek=None)
headers = {"Authorization": "Bearer " + token, "X-Metalist-Tab-Id": "tab", "Origin": "http://localhost"}
listed = client.post(API_PREFIX + "/import/scan-listing", headers=headers, json={"files": [{"path": "notes/plan.md", "size": 7}, {"path": ".DS_Store", "size": 1}]})
assert listed.status_code == 200, listed.text
assert sorted(group["key"] for group in listed.json()["groups"]) == ["hidden", "text"], listed.json()
assert client.post(API_PREFIX + "/import/scan-listing", headers=headers, json={"files": [{"path": "../x.md", "size": 1}]}).status_code == 400
started = client.post(API_PREFIX + "/import/uploads", headers=headers).json()
sent = client.post(API_PREFIX + "/import/uploads/" + started["uploadId"] + "/file", headers=headers,
                   data={"path": "notes/plan.md", "modified": "1792054800000"}, files={"file": ("plan.md", b"# Plan\\n", "text/markdown")})
assert sent.status_code == 200, sent.text
undated = client.post(API_PREFIX + "/import/uploads/" + started["uploadId"] + "/file", headers=headers,
                      data={"path": "notes/other.md"}, files={"file": ("other.md", b"x", "text/markdown")})
assert undated.status_code == 400, undated.text
old = client.post(API_PREFIX + "/import/scan", headers=headers, json={"folderPath": started["folderPath"], "changedSince": "2026-11-01"})
assert old.status_code == 400 and "No file in the folder changed since" in old.text, old.text
assert not (Path(started["folderPath"]) / "notes" / "plan.md").exists()
scanned = client.post(API_PREFIX + "/import/scan", headers=headers, json={"folderPath": started["folderPath"], "changedSince": ""})
assert [group["key"] for group in scanned.json()["groups"]] == ["text"], scanned.json()
assert client.post(API_PREFIX + "/import/uploads/" + started["uploadId"] + "/discard", headers=headers).status_code == 200
assert not Path(started["folderPath"]).exists()
'''
    environment = dict(os.environ, METALIST_DATA_DIRECTORY=str(tmp_path / "app-data"), METALIST_ENVIRONMENT="production")
    result = subprocess.run([sys.executable, "-c", script], env=environment, capture_output=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, (result.stdout + result.stderr)[-3000:]


def test_a_file_that_does_not_arrive_whole_leaves_nothing(data_directory: Path) -> None:
    upload_id, folder_path = import_uploads.start_upload()

    with pytest.raises(OSError, match="connection lost"):
        with import_uploads.receive_file(upload_id) as incoming:
            incoming.open("notes/plan.md", CHANGED_AT).write(b"part of it")
            raise OSError("connection lost")

    assert [path for path in Path(folder_path).rglob("*") if path.is_file()] == []
    assert not import_uploads.open_import_folder(Path(folder_path)).is_plain_file(PurePosixPath("notes/plan.md"))
