"""Searchable file text (docs/ready-to-build/folder-import-and-file-previews.md, "Searchable file
text"): a PDF's text kept with the file with a bloom filter of its four-letter pieces; a quoted
search finds a note by a word in a PDF it shows. The acceptance checks agreed 2026-11-01."""

from __future__ import annotations

import os
import random
import string
import typing
from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image

import app.services.file_text_search as file_text_search_module
import app.services.search_index as search_index_module
from app.db.file_session import begin_file_writer, connect_file_reader
from app.db.files_sql import delete_files, fetch_file_text
from app.models.database import SafeSession
from app.security import encryption
from app.security.encryption import clear_encryption_key, get_encryption_service, set_session_dek
from app.security.sensitive_cache import clear_sensitive_caches
from app.services.file_registry import file_registry
from app.services.file_storage import create_file, decrypt_all_files_for_plaintext, encrypt_all_files_for_active_dek
from app.services.file_text_search import (
    FILTER_PIECE_LENGTH,
    ExtractedText,
    build_filter,
    extract_file_text,
    file_texts,
    filter_may_contain,
)
from app.services.file_text_snippets import file_text_snippet
from app.services.search_index import NOTHING_INHERITED, SearchIndex, SearchRecord, extract_tags_for_search
from app.services.text_terms import text_term_matches

TOKEN = "token"
LEASE = ["Lease agreement Tenant: Sam Rivera", "Rent is due on the first of each month.", "The deposit is returned within 30 days."]


def _pdf(pages: list[str]) -> bytes:
    """A small PDF whose pages hold these lines of text (Helvetica), with a correct xref."""
    font_number = 3
    first_page_number = 4
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        font_number: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    kids = []
    for index, text in enumerate(pages):
        page_number = first_page_number + index * 2
        stream = f"BT /F1 12 Tf 20 700 Td ({text}) Tj ET".encode("latin-1")
        objects[page_number] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font_number} 0 R >> >> "
            f"/Contents {page_number + 1} 0 R >>"
        ).encode()
        objects[page_number + 1] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        kids.append(f"{page_number} 0 R")
    objects[2] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>".encode()
    out = b"%PDF-1.4\n"
    offsets = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += b"%d 0 obj\n" % number + objects[number] + b"\nendobj\n"
    xref_at = len(out)
    size = max(objects) + 1
    out += b"xref\n0 %d\n0000000000 65535 f \n" % size
    for number in range(1, size):
        out += b"%010d 00000 n \n" % offsets[number]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref_at)
    return out


def _inherits_nothing(note_ids):
    return {note_id: NOTHING_INHERITED for note_id in note_ids}


@pytest.fixture
def files(monkeypatch: pytest.MonkeyPatch):
    """An in-memory files database, no file text loaded, extraction run by the test itself."""
    SafeSession.use_memory_db()
    SafeSession.disable_read_guard()
    encryption.set_encryption_required(False)
    file_registry.reset()
    with begin_file_writer() as connection:
        connection.execute("DELETE FROM file_texts")
        connection.execute("DELETE FROM files")
    file_texts.clear()
    monkeypatch.setattr(file_texts, "refresh_in_background", lambda: None)
    yield
    file_texts.clear()


def _index(notes: dict[str, str]) -> SearchIndex:
    index = SearchIndex()
    index.attach_inherited_values_reader(_inherits_nothing)
    index.rebuild(
        [SearchRecord(note_id=note_id, content_text=text, tags="", tag_terms=extract_tags_for_search("")) for note_id, text in notes.items()],
        raw_tag_terms_by_id={note_id: frozenset() for note_id in notes},
        progress_update=lambda processed: None, progress_interval=len(notes),
    )
    return index


def _pdf_note(name: str, pages: list[str]) -> str:
    record = create_file(original_filename=name, mime_type="application/pdf", content_bytes=_pdf(pages), token=TOKEN)
    return record.id


# --- The filter ----------------------------------------------------------------------------


def test_the_filter_never_says_no_to_text_it_holds() -> None:
    rng = random.Random(7)
    text = " ".join("".join(rng.choices(string.ascii_lowercase, k=rng.randint(2, 9))) for _ in range(3000))
    bloom = build_filter(text)
    for _ in range(2000):
        start = rng.randrange(len(text) - 20)
        assert filter_may_contain(bloom, text[start:start + rng.randint(FILTER_PIECE_LENGTH, 20)])


def test_the_filter_rules_out_most_text_it_lacks_and_cant_tell_short_terms() -> None:
    text = "rent is due on the first of each month. the deposit is returned within 30 days."
    bloom = build_filter(text)
    absent = ["harbor", "zebra", "kelp wrap", "quartz", "mortgage", "volcano", "jigsaw", "xylophone"]
    assert sum(filter_may_contain(bloom, word) for word in absent) <= 1
    assert filter_may_contain(bloom, "zz")


# --- Extracting a PDF's text ---------------------------------------------------------------


def test_a_pdfs_text_is_kept_page_after_page_whitespace_collapsed() -> None:
    extracted = extract_file_text("Lease.PDF", _pdf(LEASE))
    assert extracted.text == " ".join(LEASE)
    assert extracted.is_cut is False


def test_text_past_the_cap_is_cut_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_text_search_module, "MAX_FILE_TEXT_CHARACTERS", 40)
    extracted = extract_file_text("long.pdf", _pdf(LEASE))
    assert extracted.text == " ".join(LEASE)[:40]
    assert extracted.is_cut is True


def test_a_scan_or_a_damaged_pdf_keeps_no_text() -> None:
    scanned = BytesIO()
    Image.new("RGB", (100, 100), "white").save(scanned, "PDF")
    assert extract_file_text("scan.pdf", scanned.getvalue()).text == ""
    assert extract_file_text("broken.pdf", b"not a pdf").text == ""


# --- Search (acceptance checks 1 to 4, 7) ---------------------------------------------------


@pytest.mark.parametrize(("search", "found"), [
    ('"rent is due"', {"lease-note"}),
    ('"RENT IS DUE"', {"lease-note"}),
    # Inside words, and word edges marked by spaces.
    ('"posit"', {"lease-note"}),
    ('" posit"', set()),
    ('"deposit "', {"lease-note"}),
    # By its own text or its file's.
    ('"groceries"', {"plain-note"}),
    ('"harbor"', set()),
    # Excluded: a note whose file holds the phrase is left out.
    ('"note" -"deposit"', {"plain-note"}),
])
def test_a_quoted_search_finds_a_note_by_the_text_of_a_pdf_it_shows(files, search: str, found: set[str]) -> None:
    file_id = _pdf_note("Lease.pdf", LEASE)
    file_texts.refresh()
    index = _index({"lease-note": f"Signed note ![[{file_id}]]", "plain-note": "A note about groceries"})
    assert index.query_note_ids(search) == found


def test_before_its_text_is_read_a_pdf_matches_by_name_only(files) -> None:
    file_id = _pdf_note("Lease.pdf", LEASE)
    index = _index({"lease-note": f"![[{file_id}]]"})
    assert index.query_note_ids('"rent is due"') == set()
    assert index.query_note_ids('"lease.pdf"') == {"lease-note"}
    file_texts.refresh()
    index.file_texts_changed()
    assert index.query_note_ids('"rent is due"') == {"lease-note"}


def test_results_are_exactly_those_of_reading_every_files_whole_text(files) -> None:
    rng = random.Random(3)
    vocabulary = ["tide", "pool", "harbor", "kelp", "anemone", "rent", "deposit", "lease", "crab", "storm", "a", "is"]
    pages_by_note = {f"note-{n}": [" ".join(rng.choices(vocabulary, k=40)) for _ in range(2)] for n in range(12)}
    notes = {note_id: f"![[{_pdf_note(f'{note_id}.pdf', pages)}]]" for note_id, pages in pages_by_note.items()}
    file_texts.refresh()
    index = _index(notes)
    terms = ["tide pool", "harbor kelp", "crab", "ane", "is a", "storm rent lease", "zebra", "a", "pool "]
    for term in terms:
        expected = {
            note_id for note_id, pages in pages_by_note.items()
            if text_term_matches(term, " ".join(pages).casefold()) or text_term_matches(term, f"{note_id}.pdf")
        }
        assert index.query_note_ids(f'"{term}"') == expected, term


def test_a_deleted_file_loses_its_text(files) -> None:
    file_id = _pdf_note("Lease.pdf", LEASE)
    file_texts.refresh()
    with connect_file_reader() as connection:
        assert fetch_file_text(connection, file_id) is not None
    with begin_file_writer() as connection:
        delete_files(connection, [file_id])
    with connect_file_reader() as connection:
        assert fetch_file_text(connection, file_id) is None


def test_a_pdf_without_text_is_read_once_and_matches_by_name(files) -> None:
    scanned = BytesIO()
    Image.new("RGB", (100, 100), "white").save(scanned, "PDF")
    record = create_file(original_filename="scan.pdf", mime_type="application/pdf", content_bytes=scanned.getvalue(), token=TOKEN)
    file_texts.refresh()
    assert record.id in file_texts.loaded_file_ids()
    index = _index({"scan-note": f"![[{record.id}]]"})
    assert index.query_note_ids('"scan"') == {"scan-note"}


# --- Memory (acceptance check 5) -------------------------------------------------------------


def test_login_loads_only_filters_and_locking_clears_them(files, monkeypatch: pytest.MonkeyPatch) -> None:
    file_id = _pdf_note("Lease.pdf", LEASE)
    file_texts.refresh()
    file_texts.clear()
    reads: list[str] = []
    storage = file_texts._require_storage()
    file_texts.install_storage(replace(storage, read_text=lambda read_id: reads.append(read_id)))
    try:
        file_texts.refresh()
    finally:
        file_texts.install_storage(storage)
    assert file_id in file_texts.loaded_file_ids()
    assert reads == []
    clear_sensitive_caches()
    assert file_texts.loaded_file_ids() == frozenset()


def test_the_cut_flag_is_kept(files, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_text_search_module, "MAX_FILE_TEXT_CHARACTERS", 40)
    file_id = _pdf_note("long.pdf", LEASE)
    file_texts.refresh()
    assert file_texts.is_cut(file_id) is True


def test_the_search_index_works_results_out_again_when_file_text_arrives() -> None:
    assert search_index_module.search_index.file_texts_changed in file_texts._changed_listeners


# --- Encryption (acceptance check 6) ---------------------------------------------------------


def _stored_row(file_id: str) -> dict[str, object]:
    with connect_file_reader() as connection:
        row = fetch_file_text(connection, file_id)
    assert row is not None
    return row


def test_in_a_vault_with_a_password_the_text_and_filter_are_stored_encrypted(files) -> None:
    set_session_dek(os.urandom(32))
    try:
        file_id = _pdf_note("Lease.pdf", LEASE)
        file_texts.refresh()
        row = _stored_row(file_id)
        assert row["text_encryption_nonce"] is not None
        assert b"Rent" not in typing.cast(bytes, row["text_data"])
        index = _index({"lease-note": f"![[{file_id}]]"})
        assert index.query_note_ids('"rent is due"') == {"lease-note"}
    finally:
        clear_encryption_key()


def test_adding_and_removing_a_password_rewrites_file_texts(files) -> None:
    file_id = _pdf_note("Lease.pdf", LEASE)
    file_texts.refresh()
    assert _stored_row(file_id)["text_encryption_nonce"] is None
    set_session_dek(os.urandom(32))
    try:
        service = get_encryption_service()
        encrypt_all_files_for_active_dek(encryption_service=service)
        assert _stored_row(file_id)["text_encryption_nonce"] is not None
        file_texts.clear()
        file_texts.refresh()
        assert file_texts.term_matches(file_id, "rent is due")
        decrypt_all_files_for_plaintext(encryption_service=service)
        row = _stored_row(file_id)
        assert row["text_encryption_nonce"] is None and b"Rent is due" in typing.cast(bytes, row["text_data"])
    finally:
        clear_encryption_key()


# Typeset PDFs write "ffi", "fi" and "fl" as one ligature glyph ("coeﬃcients"). Search read them
# as letters (casefold does) but the snippet did not, so Find stopped on the file with no snippet
# and marked the whole card (2026-11-02). A file's text is kept, and read, as letters.
LIGATURED = "the classical coeﬃcients of a ﬁeld"
AS_LETTERS = "the classical coefficients of a field"


def test_ligatures_in_a_pdfs_text_are_kept_as_letters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_text_search_module, "_pdf_pages", lambda content: [LIGATURED])
    assert extract_file_text("paper.pdf", b"%PDF").text == AS_LETTERS


def test_text_kept_before_with_ligatures_reads_as_letters(files) -> None:
    file_id = _pdf_note("paper.pdf", LEASE)
    file_texts.refresh()
    storage = file_texts._require_storage()
    revision = storage.searchable_files()[file_id]
    storage.store_text(file_id, ExtractedText(text=LIGATURED, is_cut=False), build_filter(LIGATURED.casefold()), revision)
    file_texts.refresh()

    assert file_texts.term_matches(file_id, "classical coef") is True
    assert file_texts.text_of(file_id) == AS_LETTERS
    assert "classical coefficients" in file_text_snippet(file_id, ("classical coef",))
