"""A download sends a segment at a time and answers Range requests, so a jump into a long file
reads only that part (docs/ready-to-build/streaming-no-file-cap.md, section 2)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from starlette.requests import Request

from app.api.routes.files import download_file_endpoint
from app.db.blob_store import BlobStore
from app.db.file_session import connect_file_reader, live_blob_store
from app.db.files_sql import fetch_file
from app.models.database import SafeSession
from app.security.encryption import clear_encryption_key, set_encryption_required, set_session_dek
from app.services.file_registry import file_registry
from app.services.file_storage import create_file, open_file_range, replace_file_content

_CONTENT = bytes(range(256)) * 1000


@pytest.fixture(params=[False, True], ids=["no-password", "password"])
def stored_file(request, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    set_encryption_required(request.param)
    if request.param:
        set_session_dek(os.urandom(32))
    file_registry.reset()
    record = create_file(original_filename="clip.mp4", mime_type="video/mp4", content_bytes=_CONTENT, token="fixture")
    yield record
    file_registry.reset()
    clear_encryption_key()
    set_encryption_required(False)


def _request(range_header: str | None) -> Request:
    headers = [(b"authorization", b"Bearer fixture")]
    if range_header is not None:
        headers.append((b"range", range_header.encode()))
    return Request({"type": "http", "method": "GET", "path": "/files/x/download", "headers": headers, "query_string": b""})


async def _body(response) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def _download(record, range_header: str | None):
    response = download_file_endpoint(_request(range_header), record.id)
    if not hasattr(response, "body_iterator"):
        return response, response.body
    return response, asyncio.run(_body(response))


def test_a_download_with_no_range_is_the_whole_file(stored_file) -> None:
    response, body = _download(stored_file, None)

    assert response.status_code == 200
    assert body == _CONTENT
    assert response.headers["content-length"] == str(len(_CONTENT))
    assert response.headers["accept-ranges"] == "bytes"
    assert "content-range" not in response.headers
    assert "attachment" in response.headers["content-disposition"]


@pytest.mark.parametrize(
    ("header", "start", "end"),
    [
        ("bytes=0-99", 0, 99),
        ("bytes=65530-65545", 65530, 65545),
        ("bytes=100000-", 100000, len(_CONTENT) - 1),
        ("bytes=-16", len(_CONTENT) - 16, len(_CONTENT) - 1),
        ("bytes=255999-999999", 255999, 255999),
    ],
)
def test_a_range_answers_exactly_those_bytes(stored_file, header: str, start: int, end: int) -> None:
    response, body = _download(stored_file, header)

    assert response.status_code == 206
    assert body == _CONTENT[start:end + 1]
    assert response.headers["content-range"] == f"bytes {start}-{end}/{len(_CONTENT)}"
    assert response.headers["content-length"] == str(end - start + 1)


def test_a_range_past_the_end_says_how_long_the_file_is(stored_file) -> None:
    response, body = _download(stored_file, f"bytes={len(_CONTENT)}-")

    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(_CONTENT)}"
    assert body == b""


def test_an_unusable_range_header_gets_the_whole_file(stored_file) -> None:
    response, body = _download(stored_file, "bytes=0-1,5-6")

    assert response.status_code == 200 and body == _CONTENT


def test_an_empty_file_downloads_as_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    set_encryption_required(False)
    file_registry.reset()
    record = create_file(original_filename="empty.txt", mime_type="text/plain", content_bytes=b"", token="fixture")

    response, body = _download(record, None)

    assert response.status_code == 200 and body == b""
    file_registry.reset()


def test_a_jump_reads_only_the_part_of_the_file_it_needs(stored_file, monkeypatch) -> None:
    blob_bytes_requested: list[int] = []
    real_open = Path.open

    def recording_open(path, *args, **kwargs):
        handle = real_open(path, *args, **kwargs)
        if path.suffix != ".mlb":
            return handle
        real_read = handle.read

        class _Counted:
            def __getattr__(self, name):
                return getattr(handle, name)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                handle.close()

            def read(self, size):
                data = real_read(size)
                blob_bytes_requested.append(len(data))
                return data

        return _Counted()

    monkeypatch.setattr(Path, "open", recording_open)

    response, body = _download(stored_file, "bytes=130000-130009")

    assert body == _CONTENT[130000:130010]
    # At most: header, the last segment (checked on open), and the one segment holding these bytes.
    assert sum(blob_bytes_requested) <= 11 + 2 * (65_536 + 16)


def test_a_file_replaced_during_a_download_finishes_with_the_bytes_it_started(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    set_encryption_required(False)
    file_registry.reset()
    before = b'{"type":"excalidraw","elements":[]}' + b" " * 3_000_000
    after = b'{"type":"excalidraw","elements":[{}]}'
    record = create_file(original_filename="d.excalidraw", mime_type="application/vnd.excalidraw+json", content_bytes=before, token="fixture")
    with connect_file_reader() as connection:
        old_blob_id = fetch_file(connection, record.id)["blob_id"]

    opened = open_file_range(file_id=record.id, token="fixture", start=0, length=len(before))
    first = next(opened.pieces)
    replace_file_content(file_id=record.id, content_bytes=after, expected_revision=1, token="fixture")

    assert live_blob_store().contains(old_blob_id)
    assert first + b"".join(opened.pieces) == before
    assert not live_blob_store().contains(old_blob_id)
    file_registry.reset()


def test_replacing_a_file_deletes_its_old_blob(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    set_encryption_required(False)
    file_registry.reset()
    record = create_file(
        original_filename="d.excalidraw", mime_type="application/vnd.excalidraw+json",
        content_bytes=b'{"type":"excalidraw","elements":[]}', token="fixture",
    )
    with connect_file_reader() as connection:
        old_blob_id = fetch_file(connection, record.id)["blob_id"]

    replace_file_content(file_id=record.id, content_bytes=b'{"type":"excalidraw","elements":[{}]}', expected_revision=1, token="fixture")

    assert not live_blob_store().contains(old_blob_id)
    file_registry.reset()


def test_a_stale_revision_leaves_no_new_blob_behind(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    set_encryption_required(False)
    file_registry.reset()
    record = create_file(
        original_filename="d.excalidraw", mime_type="application/vnd.excalidraw+json",
        content_bytes=b'{"type":"excalidraw","elements":[]}', token="fixture",
    )
    written: list[str] = []
    real_write = BlobStore.write

    def record_write(store, content, *, is_encrypted):
        stored = real_write(store, content, is_encrypted=is_encrypted)
        written.append(stored.blob_id)
        return stored

    monkeypatch.setattr(BlobStore, "write", record_write)

    with pytest.raises(Exception, match="revision"):
        replace_file_content(file_id=record.id, content_bytes=b'{"type":"excalidraw","elements":[{}]}', expected_revision=2, token="fixture")

    assert written == [], "a conflict found before writing writes nothing"
    file_registry.reset()
