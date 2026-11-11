"""A PDF's first page as a picture, for galleries (docs/future-plans/gallery.md, "PDF first pages")."""
from __future__ import annotations

import io
import os
import sqlite3
from types import SimpleNamespace

import pytest
from PIL import Image

import app.services.pdf_first_pages as pdf_first_pages_module
from app.db.file_schema import initialize_file_schema
from app.db.file_session import begin_file_writer, connect_file_reader
from app.db.files_sql import fetch_all_blob_ids, fetch_every_blob_id_of_files, fetch_file_first_page
from app.models.database import SafeSession
from app.security import encryption
from app.security.encryption import clear_encryption_key, get_encryption_service, set_session_dek
from app.security.rendered_html import sanitize_rendered_html
from app.services.embedded_references import _render_pdf_tile
from app.services.file_registry import file_registry
from app.services.file_storage import (
    FilePreviewMissing,
    create_file,
    decrypt_all_files_for_plaintext,
    encrypt_all_files_for_active_dek,
    get_file_first_page,
    get_file_reference_record,
)
from app.services.pdf_first_page_worker import DRAWN_WIDTH_PIXELS, draw_first_page
from app.services.pdf_first_pages import pdf_first_pages

TOKEN = "token"
_JPEG_START = b"\xff\xd8"


def _pdf() -> bytes:
    """A one-page PDF: a blue band over grey lines, as a document's title over its text."""
    page = Image.new("RGB", (850, 1100), "white")
    for line in range(10):
        page.paste((200, 200, 200), (60, 260 + line * 60, 790, 290 + line * 60))
    page.paste((30, 80, 160), (60, 60, 790, 200))
    out = io.BytesIO()
    page.save(out, "PDF", resolution=100)
    return out.getvalue()


@pytest.fixture
def files():
    """An in-memory files database; drawing is run by the test itself (conftest stops the background)."""
    SafeSession.use_memory_db()
    SafeSession.disable_read_guard()
    encryption.set_encryption_required(False)
    file_registry.reset()
    with begin_file_writer() as connection:
        connection.execute("DELETE FROM file_first_pages")
        connection.execute("DELETE FROM files")
    yield


def _store_pdf(name: str, content: bytes) -> str:
    return create_file(original_filename=name, mime_type="application/pdf", content_bytes=content, token=TOKEN).id


def test_the_worker_draws_the_first_page_as_a_jpeg_the_drawn_width() -> None:
    drawn = draw_first_page(_pdf())
    assert drawn.startswith(_JPEG_START)
    # PDFium rounds the page's size up to whole pixels.
    assert Image.open(io.BytesIO(drawn)).width in (DRAWN_WIDTH_PIXELS, DRAWN_WIDTH_PIXELS + 1)


def test_the_worker_answers_nothing_for_a_pdf_it_cannot_read() -> None:
    assert draw_first_page(b"%PDF-1.4 not really a pdf") == b""


def test_a_stored_pdf_gets_its_first_page_once_drawn(files) -> None:
    file_id = _store_pdf("manual.pdf", _pdf())
    assert get_file_reference_record(file_id, TOKEN).first_page_revision == 0
    revision = pdf_first_pages.revision()

    pdf_first_pages.refresh()

    assert get_file_reference_record(file_id, TOKEN).first_page_revision == 1
    first_page = get_file_first_page(file_id=file_id, token=TOKEN)
    assert first_page.mime_type == "image/jpeg" and first_page.content_bytes.startswith(_JPEG_START)
    # The page's status check sees it, and draws the notes showing that PDF again.
    assert pdf_first_pages.revision() > revision
    assert pdf_first_pages.pending() == []


def test_a_pdf_that_cannot_be_drawn_has_no_picture_and_is_not_tried_again(files) -> None:
    file_id = _store_pdf("broken.pdf", b"%PDF-1.4 not really a pdf")

    pdf_first_pages.refresh()

    assert get_file_reference_record(file_id, TOKEN).first_page_revision == 0
    with pytest.raises(FilePreviewMissing):
        get_file_first_page(file_id=file_id, token=TOKEN)
    assert pdf_first_pages.pending() == []


def test_a_new_drawing_draws_every_first_page_again(files, monkeypatch) -> None:
    file_id = _store_pdf("manual.pdf", _pdf())
    pdf_first_pages.refresh()
    monkeypatch.setattr(pdf_first_pages_module, "DRAWER_VERSION", pdf_first_pages_module.DRAWER_VERSION + 1)

    assert pdf_first_pages.pending() == [(file_id, 1)]


def test_only_pdfs_are_drawn(files) -> None:
    create_file(original_filename="notes.txt", mime_type="text/plain", content_bytes=b"just text", token=TOKEN)
    assert pdf_first_pages.pending() == []


def test_with_a_password_the_page_is_encrypted_and_rewritten_with_the_password(files) -> None:
    file_id = _store_pdf("manual.pdf", _pdf())
    pdf_first_pages.refresh()
    set_session_dek(os.urandom(32))
    try:
        service = get_encryption_service()
        encrypt_all_files_for_active_dek(encryption_service=service)
        with connect_file_reader() as connection:
            assert fetch_file_first_page(connection, file_id)["blob_seal_encryption_nonce"] is not None
        assert get_file_first_page(file_id=file_id, token=TOKEN).content_bytes.startswith(_JPEG_START)
        decrypt_all_files_for_plaintext(encryption_service=service)
        with connect_file_reader() as connection:
            assert fetch_file_first_page(connection, file_id)["blob_seal_encryption_nonce"] is None
        assert get_file_first_page(file_id=file_id, token=TOKEN).content_bytes.startswith(_JPEG_START)
    finally:
        clear_encryption_key()


def test_deleting_a_pdf_also_frees_its_first_page(files) -> None:
    file_id = _store_pdf("manual.pdf", _pdf())
    pdf_first_pages.refresh()
    with connect_file_reader() as connection:
        page_blob = fetch_file_first_page(connection, file_id)["blob_id"]
        assert page_blob in fetch_every_blob_id_of_files(connection, [file_id])


def test_a_catalog_from_before_version_18_lists_its_blobs_without_first_pages() -> None:
    connection = sqlite3.connect(":memory:")
    initialize_file_schema(connection)
    connection.execute("DROP TABLE file_first_pages")
    connection.execute(
        "INSERT INTO files (id, title, metadata_json, blob_id, blob_seal, created_at, updated_at) "
        "VALUES ('report', 'report.pdf', '{}', 'blob-1', x'00', 'now', 'now')"
    )
    assert fetch_all_blob_ids(connection) == {"blob-1"}


def _record(first_page_revision: int) -> SimpleNamespace:
    return SimpleNamespace(title="manual.pdf", thumbnail_kind="pdf", first_page_revision=first_page_revision)


def test_a_drawn_pdf_tile_loads_its_first_page_and_survives_sanitizing() -> None:
    tile = sanitize_rendered_html(_render_pdf_tile(record=_record(1), file_id="abc", static_export=False))
    assert 'data-picture-source="first-page"' in tile
    assert 'class="note-file-image-preview"' in tile


@pytest.mark.parametrize(("first_page_revision", "static_export"), [(0, False), (1, True)], ids=["not-drawn", "export"])
def test_a_pdf_without_its_first_page_shows_its_badge_and_name(first_page_revision: int, static_export: bool) -> None:
    tile = _render_pdf_tile(record=_record(first_page_revision), file_id="abc", static_export=static_export)
    assert "data-picture-source" not in tile
    assert ">PDF<" in tile and "manual.pdf" in tile
