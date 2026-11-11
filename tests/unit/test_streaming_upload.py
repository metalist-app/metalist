"""A file of any size comes in as it arrives (docs/design/file-storage.md): straight
into encrypted storage, never whole in memory or plaintext in a temporary file, and refused plainly
when it won't fit."""

from __future__ import annotations

import asyncio
from collections import namedtuple
import errno
import os
from pathlib import Path
import tracemalloc

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import pytest
from starlette import formparsers

from app.api import streaming_upload
from app.api.routes import files as files_routes
from app.api.transactions import transactional_route
from app.api.routes.files import router as files_router
from app.api.streaming_upload import receive_upload
from app.db import session as session_module
from app.db.blob_store import BlobStore, most_stored_bytes, padded_size
from app.db.file_session import begin_file_writer, connect_file_reader, live_blob_store
from app.db.files_sql import AttachmentSizeExceeded, fetch_file
from app.models.database import SafeSession
from app.security.encryption import clear_encryption_key, set_encryption_required, set_session_dek
from app.services import disk_space, email_cards, email_search_text, file_storage, file_text_search
from app.services.file_registry import file_registry
from app.services.file_storage import create_file, download_file, open_file_upload, read_stored_file
from app.services.input_errors import InputRejected

_HEADERS = {"Authorization": "Bearer fixture"}
_BOUNDARY = "testboundary"
_Usage = namedtuple("_Usage", "total used free")


@pytest.fixture(autouse=True)
def _no_file_outlives_its_test():
    """The in-memory catalog is shared: a row encrypted by one test can't be read by the next."""
    yield
    SafeSession.use_memory_db()
    with begin_file_writer() as connection:
        connection.execute("DELETE FROM files")


def _form(*parts: bytes) -> bytes:
    return b"".join(parts) + f"--{_BOUNDARY}--\r\n".encode()


def _file_part_of_type(name: str, content: bytes, *, content_type: str) -> bytes:
    header = f'--{_BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: {content_type}\r\n\r\n'
    return header.encode() + content + b"\r\n"


def _file_part(name: str, content: bytes) -> bytes:
    return _file_part_of_type(name, content, content_type="text/plain")


def _text_part(name: str, value: str) -> bytes:
    return f'--{_BOUNDARY}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()


class _Collected:
    def __init__(self) -> None:
        self.pieces: list[bytes] = []

    def write(self, content: bytes) -> None:
        self.pieces.append(content)


def _echo_client() -> tuple[TestClient, _Collected]:
    collected = _Collected()
    app = FastAPI()

    @app.exception_handler(InputRejected)
    async def rejected(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.post("/upload")
    @transactional_route
    async def upload(request: Request) -> dict[str, object]:
        part, fields = await receive_upload(request, open_sink=lambda _part, _fields: collected)
        return {"name": part.filename, "type": part.content_type, "fields": fields}

    return TestClient(app), collected


def _post(client: TestClient, body: bytes):
    return client.post("/upload", content=body, headers={"Content-Type": f"multipart/form-data; boundary={_BOUNDARY}"})


def test_a_form_is_read_as_it_arrives() -> None:
    client, collected = _echo_client()

    response = _post(client, _form(_text_part("path", "notes/a.md"), _file_part("a.md", b"line one\r\nline two")))

    assert response.status_code == 200
    assert response.json() == {"name": "a.md", "type": "text/plain", "fields": {"path": "notes/a.md"}}
    assert b"".join(collected.pieces) == b"line one\r\nline two"


def test_the_fields_sent_before_the_file_are_there_when_it_opens() -> None:
    seen: list[dict[str, str]] = []
    app = FastAPI()

    @app.post("/upload")
    @transactional_route
    async def upload(request: Request) -> dict[str, str]:
        def open_sink(_part, fields):
            seen.append(dict(fields))
            return _Collected()

        await receive_upload(request, open_sink=open_sink)
        return {}

    _post(TestClient(app), _form(_text_part("path", "a/b.md"), _file_part("b.md", b"x")))

    assert seen == [{"path": "a/b.md"}]


@pytest.mark.parametrize("split_at", [1, 7, 40, 90, 120])
def test_a_body_arriving_in_any_pieces_reads_the_same(split_at: int) -> None:
    client, collected = _echo_client()
    body = _form(_file_part("a.bin", bytes(range(256))))

    def chunks():
        for start in range(0, len(body), split_at):
            yield body[start:start + split_at]

    response = client.post("/upload", content=chunks(), headers={"Content-Type": f"multipart/form-data; boundary={_BOUNDARY}"})

    assert response.status_code == 200
    assert b"".join(collected.pieces) == bytes(range(256))


def test_a_name_outside_ascii_survives() -> None:
    client, _collected_pieces = _echo_client()

    response = _post(client, _form(_file_part("rés—umé 日本.pdf", b"x")))

    assert response.json()["name"] == "rés—umé 日本.pdf"


@pytest.mark.parametrize(
    ("body", "status", "detail"),
    [
        (_form(_text_part("path", "only text")), 422, "must include a file"),
        (_form(_file_part("", b"x")), 400, "filename"),
        (_form(_file_part_of_type("a.txt", b"x", content_type="")), 400, "MIME"),
        (_form(_file_part("a.txt", b"x"), _file_part("b.txt", b"y")), 400, "one file"),
        (_form(_text_part("path", "x" * 70_000), _file_part("a.txt", b"x")), 400, "read"),
    ],
    # Named by case: pytest keeps the running test's name in an environment variable, which
    # Windows caps at 32,767 characters.
    ids=["no-file", "no-filename", "no-type", "two-files", "long-text-field"],
)
def test_a_form_that_cannot_be_used_says_why(body: bytes, status: int, detail: str) -> None:
    client, _collected_pieces = _echo_client()

    response = _post(client, body)

    assert response.status_code == status
    assert detail in response.json()["detail"]


def test_a_body_cut_short_is_not_a_whole_file() -> None:
    client, _collected_pieces = _echo_client()

    response = _post(client, _file_part("a.txt", b"only part of it"))

    assert response.status_code == 400 and "interrupted" in response.json()["detail"]


def test_a_request_that_is_not_a_form_is_refused() -> None:
    client, _collected_pieces = _echo_client()

    response = client.post("/upload", content=b"plain", headers={"Content-Type": "text/plain"})

    assert response.status_code == 400


@pytest.fixture(params=[False, True], ids=["no-password", "password"])
def vault(request, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    set_encryption_required(request.param)
    if request.param:
        set_session_dek(os.urandom(32))
    file_registry.reset()
    monkeypatch.setattr(disk_space.shutil, "disk_usage", lambda _path: _Usage(10**13, 0, 10**13))
    app = FastAPI()
    app.include_router(files_router)

    @app.exception_handler(InputRejected)
    async def rejected(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    yield TestClient(app, raise_server_exceptions=False)
    file_registry.reset()
    clear_encryption_key()
    set_encryption_required(False)


def _upload(client: TestClient, name: str, content: bytes):
    return client.post("/files/upload", headers=_HEADERS, files={"file": (name, content, "video/mp4")})


def test_a_file_over_the_old_limit_comes_in_and_downloads_whole(vault, monkeypatch) -> None:
    monkeypatch.setattr(file_storage, "MAX_IN_MEMORY_FILE_BYTES", 10)
    monkeypatch.setattr(files_routes, "MAX_IN_MEMORY_FILE_BYTES", 10)
    content = os.urandom(200_000)

    response = _upload(vault, "clip.mp4", content)

    assert response.status_code == 200, response.text
    assert response.json()["size_bytes"] == len(content)
    file_id = response.json()["file_id"]
    assert vault.get(f"/files/{file_id}/download", headers=_HEADERS).content == content


def test_a_vault_with_a_password_never_stores_the_upload_readable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    set_encryption_required(True)
    set_session_dek(os.urandom(32))
    file_registry.reset()
    try:
        with open_file_upload(token="fixture") as upload:
            upload.write(b"a secret sentence")
            record = upload.finish(original_filename="a.txt", mime_type="text/plain")
        with connect_file_reader() as connection:
            blob_id = fetch_file(connection, record.id)["blob_id"]
        assert b"a secret sentence" not in live_blob_store().path_of(blob_id).read_bytes()
    finally:
        file_registry.reset()
        clear_encryption_key()
        set_encryption_required(False)


def test_an_upload_never_spools_to_a_temporary_file(vault, monkeypatch) -> None:
    def refuse(*_args, **_kwargs):
        raise AssertionError("an upload was spooled to a temporary file")

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", refuse)

    assert _upload(vault, "clip.mp4", os.urandom(3_000_000)).status_code == 200


def test_an_upload_cut_short_leaves_nothing_behind(vault) -> None:
    body = _file_part("a.bin", os.urandom(300_000))
    written_before = set(live_blob_store().directory.glob("*/*"))

    response = vault.post(
        "/files/upload", content=body, headers={**_HEADERS, "Content-Type": f"multipart/form-data; boundary={_BOUNDARY}"},
    )

    assert response.status_code == 400
    assert set(live_blob_store().directory.glob("*/*")) == written_before


def test_writing_a_large_upload_holds_only_a_piece_or_so_in_memory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    set_encryption_required(False)
    file_registry.reset()
    piece = os.urandom(64 * 1024)
    with open_file_upload(token="fixture") as upload:
        tracemalloc.start()
        for _ in range(500):
            upload.write(piece)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        record = upload.finish(original_filename="big.bin", mime_type="application/octet-stream")

    assert peak < 512 * 1024
    assert record.size_bytes == 500 * len(piece)
    file_registry.reset()


def _with_free(monkeypatch, *, total: int, free: int) -> None:
    monkeypatch.setattr(disk_space.shutil, "disk_usage", lambda _path: _Usage(total, total - free, free))


GIB = 1024 ** 3


def test_a_file_that_fits_with_the_reserve_to_spare_is_allowed(monkeypatch) -> None:
    _with_free(monkeypatch, total=500 * GIB, free=3 * GIB)

    disk_space.require_room_for_files([GIB])


def test_a_file_that_would_eat_the_reserve_is_refused_saying_how_much_is_missing(monkeypatch) -> None:
    _with_free(monkeypatch, total=500 * GIB, free=2 * GIB)

    with pytest.raises(InputRejected, match=r"about 1\.\d GB more"):
        disk_space.require_room_for_files([2 * GIB])


def test_on_a_small_disk_the_reserve_is_five_percent(monkeypatch) -> None:
    total = 10 * GIB
    size = GIB
    free_just_enough = most_stored_bytes(size) + total // 20
    _with_free(monkeypatch, total=total, free=free_just_enough)
    disk_space.require_room_for_files([size])

    _with_free(monkeypatch, total=total, free=free_just_enough - 1)
    with pytest.raises(InputRejected, match="more"):
        disk_space.require_room_for_files([size])


def test_the_room_counted_covers_the_largest_a_file_can_be_stored(tmp_path: Path) -> None:
    store = BlobStore(tmp_path / "blobs")
    for size in (0, 1, 1000, 65_536, 70_000, 2_000_000):
        stored = store.write(os.urandom(size), is_encrypted=True)
        assert store.stored_size(stored.blob_id) <= most_stored_bytes(size)
        assert most_stored_bytes(size) >= padded_size(size)


def test_an_upload_that_will_not_fit_is_refused_before_a_byte_is_stored(vault, monkeypatch) -> None:
    _with_free(monkeypatch, total=500 * GIB, free=GIB)
    before = set(live_blob_store().directory.glob("*/*"))

    response = _upload(vault, "clip.mp4", b"x" * 1000)

    assert response.status_code == 400 and "more" in response.json()["detail"]
    assert set(live_blob_store().directory.glob("*/*")) == before


def test_a_disk_that_fills_while_writing_gives_the_plain_message_and_keeps_nothing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    set_encryption_required(False)
    file_registry.reset()
    before = set(live_blob_store().directory.glob("*/*"))

    with pytest.raises(InputRejected, match="filled up"):
        with disk_space.full_disk_is_rejected(), open_file_upload(token="fixture") as upload:
            upload.write(b"part")
            raise OSError(errno.ENOSPC, "No space left on device")

    assert set(live_blob_store().directory.glob("*/*")) == before
    file_registry.reset()


def test_any_other_disk_error_stays_an_error() -> None:
    with pytest.raises(PermissionError):
        with disk_space.full_disk_is_rejected():
            raise PermissionError(errno.EACCES, "denied")


@pytest.fixture
def plain_vault(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    set_encryption_required(False)
    file_registry.reset()
    monkeypatch.setattr(file_storage, "MAX_IN_MEMORY_FILE_BYTES", 10)
    yield
    file_registry.reset()


def test_a_file_too_large_to_hold_in_memory_is_read_for_nothing_automatic(plain_vault) -> None:
    record = create_file(original_filename="big.eml", mime_type="message/rfc822", content_bytes=b"x" * 11, token="fixture")

    assert read_stored_file(record.id) is None


def test_an_email_too_large_to_hold_shows_its_file_name_and_adds_no_words(plain_vault, monkeypatch) -> None:
    record = create_file(original_filename="big.eml", mime_type="message/rfc822", content_bytes=b"x" * 11, token="fixture")

    assert email_cards.email_card_name.__wrapped__(record.id) == ""
    assert email_search_text.email_search_words.__wrapped__(record.id) == ""


def test_opening_a_file_too_large_to_hold_says_to_download_it(plain_vault) -> None:
    record = create_file(original_filename="big.bin", mime_type="application/octet-stream", content_bytes=b"x" * 11, token="fixture")

    with pytest.raises(AttachmentSizeExceeded, match="Download it instead"):
        download_file(record.id, "fixture")


def test_the_viewer_says_too_large_instead_of_reading_it(vault, monkeypatch) -> None:
    monkeypatch.setattr(files_routes, "MAX_IN_MEMORY_FILE_BYTES", 10)
    file_id = _upload_named(vault, "big.txt", b"x" * 11)

    answer = vault.get(f"/files/{file_id}/view", headers=_HEADERS).json()

    assert (answer["kind"], answer["status"], answer["html"]) == ("page", "too_large", "")


def _upload_named(client: TestClient, name: str, content: bytes) -> str:
    response = client.post("/files/upload", headers=_HEADERS, files={"file": (name, content, "text/plain")})
    assert response.status_code == 200, response.text
    return response.json()["file_id"]


def test_a_file_too_large_to_read_keeps_no_text_and_is_not_tried_again(plain_vault) -> None:
    record = create_file(original_filename="big.txt", mime_type="text/plain", content_bytes=b"needle " * 2, token="fixture")
    file_text_search.file_texts.clear()

    file_text_search.file_texts.extract_and_store(record.id, 1)

    stored = file_storage._read_file_text(record.id)
    assert stored is not None
    assert (stored.text, stored.is_cut, stored.content_revision) == ("", True, 1)
    assert file_registry.title_of(record.id) == "big.txt"


def test_reading_the_body_does_not_carry_the_open_transaction_to_the_connection() -> None:
    """Reading can make the event loop resume the connection's reader, and the loop keeps the
    context it was resumed in for every later request on that connection: the next request
    then found a transaction "already active" (a real 500, after a large upload)."""
    seen_while_reading: list[object] = []

    async def body():
        seen_while_reading.append(session_module._request_transaction_state.get())
        yield b"chunk"

    async def read_inside_a_transaction() -> bytes:
        with session_module.begin_request_transaction():
            return await streaming_upload._next_chunk(body())

    assert asyncio.run(read_inside_a_transaction()) == b"chunk"
    assert seen_while_reading == [None]
