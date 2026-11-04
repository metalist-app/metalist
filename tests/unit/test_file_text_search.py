"""Searchable file text (docs/ready-to-build/folder-import-and-file-previews.md, "Searchable file
text"): a PDF's text kept with the file with a bloom filter of its four-letter pieces; a quoted
search finds a note by a word in a PDF it shows. The acceptance checks agreed 2026-11-01."""

from __future__ import annotations

import os
import random
import string
import typing
import zipfile
from dataclasses import replace
from pathlib import Path
from threading import Thread
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

import app.services.file_text_search as file_text_search_module
import app.services.search_index as search_index_module
import app.services.snapshot as snapshot_module
from app.db.file_session import begin_file_writer, connect_file_reader
from app.db.files_sql import delete_files, fetch_file_text
from app.models.database import SafeSession
from app.security import encryption
from app.security.encryption import clear_encryption_key, get_encryption_service, set_session_dek
from app.security.sensitive_cache import clear_sensitive_caches, disable_and_clear_sensitive_caches, enable_sensitive_caches
from app.services.background_work import background_work
from app.services.file_registry import file_registry
from app.services.file_storage import create_file, decrypt_all_files_for_plaintext, encrypt_all_files_for_active_dek
from app.services.file_text_search import (
    FILTER_PIECE_LENGTH,
    FILTER_VERSION,
    TEXT_READER_VERSIONS,
    ExtractedText,
    KeptText,
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
    disable_and_clear_sensitive_caches()
    try:
        assert file_texts.loaded_file_ids() == frozenset()
        assert not file_texts.term_matches(file_id, "rent is due")
    finally:
        enable_sensitive_caches()


def test_filters_emptied_by_logging_in_load_again_when_next_asked(files) -> None:
    # Logging in empties the loaded filters (a sensitive cache) after startup loaded them, and
    # nothing loaded them again: after a restart no quoted search or find saw any file's text
    # (the maintainer, 2026-11-03: "neuropsychiatric disorders", 0 results).
    file_id = _pdf_note("Lease.pdf", LEASE)
    file_texts.refresh()
    clear_sensitive_caches()
    assert file_texts.term_matches(file_id, "rent is due")
    assert file_id in file_texts.loaded_file_ids()
    clear_sensitive_caches()
    index = _index({"lease-note": f"Signed ![[{file_id}]]"})
    assert index.query_note_ids('"rent is due"') == {"lease-note"}


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
    monkeypatch.setattr(file_text_search_module, "_file_pages", lambda extension, content: [LIGATURED])
    assert extract_file_text("paper.pdf", b"%PDF").text == AS_LETTERS


def test_text_kept_before_with_ligatures_reads_as_letters(files) -> None:
    file_id = _pdf_note("paper.pdf", LEASE)
    file_texts.refresh()
    storage = file_texts._require_storage()
    revision = storage.searchable_files()[file_id]
    storage.store_text(file_id, KeptText(
        extracted=ExtractedText(text=LIGATURED, is_cut=False), filter_bytes=build_filter(LIGATURED.casefold()),
        content_revision=revision, reader_version=TEXT_READER_VERSIONS[".pdf"], filter_version=FILTER_VERSION,
    ))
    file_texts.refresh()

    assert file_texts.term_matches(file_id, "classical coef") is True
    assert file_texts.text_of(file_id) == AS_LETTERS
    assert "classical coefficients" in file_text_snippet(file_id, ("classical coef",))


# --- In the background, visibly, resumably (the maintainer, 2026-11-02) ------------------------


# A PDF's text can hold halves of a character (UTF-16 surrogates; "Paolo Bo\ude02etta" in a
# real paper): encoding it for the filter failed, which ended the reading thread at that file
# on every start, so no file after it was ever read (the maintainer's vault, 2026-11-03: 100
# of 1,590 files read, no search or find saw the rest).
BROKEN_PAGE = "Paolo Bo\ude02etta measured \ud835\udc00 cohorts"


def test_a_lone_half_of_a_character_reads_as_a_replacement_and_a_split_pair_as_its_character(
    files, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(file_text_search_module, "_file_pages", lambda ending, content: [BROKEN_PAGE])
    extracted = extract_file_text("paper.pdf", b"%PDF-")
    assert extracted.text == "Paolo Bo\ufffdetta measured A cohorts"
    assert build_filter(extracted.text.casefold())


def test_a_file_with_broken_characters_doesnt_stop_the_files_after_it_being_read(
    files, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = [_pdf_note(name, LEASE) for name in ("One.pdf", "Two.pdf", "Three.pdf")]
    real_pages = file_text_search_module._file_pages
    reads: list[str] = []

    def first_read_broken(ending: str, content: bytes):
        reads.append(ending)
        if len(reads) == 1:
            return [BROKEN_PAGE]
        return real_pages(ending, content)

    monkeypatch.setattr(file_text_search_module, "_file_pages", first_read_broken)
    file_texts.refresh()
    assert len(reads) == len(ids)
    assert set(ids) <= file_texts.loaded_file_ids()
    assert sum(file_texts.term_matches(file_id, "rent is due") for file_id in ids) == len(ids) - 1


def test_pdfs_are_read_in_a_process_of_their_own(files, monkeypatch: pytest.MonkeyPatch) -> None:
    # pypdf in the server's process starved every request while it read (a 4 KB image waited
    # 10 to 15 seconds behind 15 MB of PDFs).
    assert "PdfReader" not in vars(file_text_search_module)
    calls: list[list[str]] = []
    real_run = file_text_search_module.subprocess.run
    monkeypatch.setattr(file_text_search_module.subprocess, "run", lambda command, **options: calls.append(command) or real_run(command, **options))
    _pdf_note("Lease.pdf", LEASE)
    file_texts.refresh()
    assert [command[1:3] for command in calls] == [["-m", "app.services.file_text_worker"]]


def test_reading_pdfs_is_listed_with_how_many_are_read(files, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[dict[str, object]]] = []
    for name in ("One.pdf", "Two.pdf", "Three.pdf"):
        _pdf_note(name, LEASE)
    real_store = file_texts._require_storage().store_text
    storage = file_texts._require_storage()
    file_texts.install_storage(replace(storage, store_text=lambda *args: (seen.append(background_work.snapshot()), real_store(*args))))
    try:
        file_texts.refresh()
    finally:
        file_texts.install_storage(storage)
    assert [[(entry["label"], entry["done"], entry["total"]) for entry in snapshot] for snapshot in seen] == [
        [("Reading document text", 0, 3)], [("Reading document text", 1, 3)], [("Reading document text", 2, 3)],
    ]
    assert background_work.snapshot() == []


def test_reading_stopped_halfway_goes_on_with_the_pdfs_not_read_yet(files, monkeypatch: pytest.MonkeyPatch) -> None:
    ids = [_pdf_note(name, LEASE) for name in ("One.pdf", "Two.pdf", "Three.pdf")]
    real_extract = file_text_search_module.extract_file_text
    read: list[str] = []

    def stop_after_two(file_name: str, content: bytes):
        if len(read) == 2:
            raise KeyboardInterrupt("the server stopped")
        read.append(file_name)
        return real_extract(file_name, content)

    monkeypatch.setattr(file_text_search_module, "extract_file_text", stop_after_two)
    with pytest.raises(KeyboardInterrupt):
        file_texts.refresh()
    assert background_work.snapshot() == []
    file_texts.clear()
    monkeypatch.setattr(file_text_search_module, "extract_file_text", lambda file_name, content: (read.append(file_name), real_extract(file_name, content))[1])
    file_texts.refresh()
    assert len(read) == 3 and set(read) == {"One.pdf", "Two.pdf", "Three.pdf"}, f"after the stop, only the PDF not read yet is read: {read}"
    assert set(ids) <= file_texts.loaded_file_ids()


def test_reading_pdfs_waits_for_an_import_to_finish(files) -> None:
    # What shows on the page first: an import's notes and images, then the PDFs' text (the
    # maintainer, 2026-11-02).
    _pdf_note("Lease.pdf", LEASE)
    order: list[str] = []
    with background_work.track("import", "Importing files", total=1) as progress:
        worker = Thread(target=lambda: (file_texts.refresh_waiting_for_imports(), order.append("read")))
        worker.start()
        worker.join(timeout=0.3)
        order.append("import done")
        progress.advance()
    worker.join()
    assert order == ["import done", "read"]


# --- Word documents and RTFs (the maintainer, 2026-11-02: ⌘F found nothing inside an RTF) -----


def _word_document(text: str) -> bytes:
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("word/document.xml", (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
            f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"))
    return out.getvalue()


@pytest.mark.parametrize(("name", "mime_type", "content", "phrase"), [
    ("Harold and Lupus.rtf", "application/octet-stream", rb"{\rtf1\ansi{\fonttbl{\f0 Times;}}\f0 Lupus waited by the harbor gate.\par}", '"harbor gate"'),
    # As a browser sends an RTF dropped from the Mac's desktop.
    ("Harold and Lupus.rtf", "text/rtf", rb"{\rtf1\ansi{\fonttbl{\f0 Times;}}\f0 Lupus waited by the harbor gate.\par}", '"harbor gate"'),
    ("Harold and Lupus.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", _word_document("Lupus waited by the harbor gate."), '"harbor gate"'),
    # Word 97-2003 (written by macOS textutil): read since 2026-11-03.
    ("Harbor plan.doc", "application/msword", (Path(__file__).resolve().parents[1] / "fixtures" / "word97" / "plan.doc").read_bytes(), '"ledger’s copy"'),
])
def test_a_quoted_search_finds_a_note_by_the_text_of_a_word_document_or_rtf_it_shows(files, name: str, mime_type: str, content: bytes, phrase: str) -> None:
    record = create_file(original_filename=name, mime_type=mime_type, content_bytes=content, token=TOKEN)
    file_texts.refresh()
    index = _index({"story-note": f"![[{record.id}]]", "plain-note": "A note about groceries"})
    assert index.query_note_ids(phrase) == {"story-note"}
    assert index.query_note_ids('"Times"') == set(), "an RTF's font table is no text of it"


def test_a_damaged_word_document_keeps_no_text_and_matches_by_name(files) -> None:
    record = create_file(original_filename="broken.docx", mime_type="application/octet-stream", content_bytes=b"not a zip", token=TOKEN)
    file_texts.refresh()
    assert record.id in file_texts.loaded_file_ids()
    index = _index({"note": f"![[{record.id}]]"})
    assert index.query_note_ids('"broken"') == {"note"}


# --- Versions (the maintainer, 2026-11-03: "anytime there's an update to one of those algorithms
# for a file format, we should go back and recalculate all of it for all of those of that type") --

RTF = rb"{\rtf1\ansi{\fonttbl{\f0 Times;}}\f0 Lupus waited by the harbor gate.\par}"


def _stored_versions(file_id: str) -> tuple[int, int]:
    with connect_file_reader() as connection:
        row = connection.execute("SELECT reader_version, filter_version FROM file_texts WHERE file_id = ?", (file_id,)).fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


def _counting_reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    read: list[str] = []
    real_extract = file_text_search_module.extract_file_text

    def counted(file_name: str, content: bytes):
        read.append(file_name)
        return real_extract(file_name, content)

    monkeypatch.setattr(file_text_search_module, "extract_file_text", counted)
    return read


def test_kept_text_records_the_reader_and_filter_that_made_it(files) -> None:
    file_id = _pdf_note("Lease.pdf", LEASE)
    file_texts.refresh()
    assert _stored_versions(file_id) == (TEXT_READER_VERSIONS[".pdf"], FILTER_VERSION)


def test_a_newer_reader_reads_every_file_of_its_kind_again_and_no_other(files, monkeypatch: pytest.MonkeyPatch) -> None:
    pdfs = [_pdf_note(name, LEASE) for name in ("One.pdf", "Two.pdf")]
    rtf = create_file(original_filename="Story.rtf", mime_type="text/rtf", content_bytes=RTF, token=TOKEN).id
    file_texts.refresh()
    read = _counting_reads(monkeypatch)
    monkeypatch.setitem(TEXT_READER_VERSIONS, ".pdf", TEXT_READER_VERSIONS[".pdf"] + 1)

    file_texts.refresh()

    assert sorted(read) == ["One.pdf", "Two.pdf"]
    assert [_stored_versions(file_id)[0] for file_id in pdfs] == [TEXT_READER_VERSIONS[".pdf"]] * 2
    assert _stored_versions(rtf) == (TEXT_READER_VERSIONS[".rtf"], FILTER_VERSION)
    read.clear()
    file_texts.refresh()
    assert read == [], "read once per version"


def test_a_newer_readers_text_is_what_search_reads(files, monkeypatch: pytest.MonkeyPatch) -> None:
    file_id = _pdf_note("Lease.pdf", LEASE)
    file_texts.refresh()
    assert file_texts.term_matches(file_id, "rent is due") is True
    monkeypatch.setattr(file_text_search_module, "_file_pages", lambda extension, content: ["A better reading of the harbor gate"])
    monkeypatch.setitem(TEXT_READER_VERSIONS, ".pdf", TEXT_READER_VERSIONS[".pdf"] + 1)

    file_texts.refresh()

    assert file_texts.term_matches(file_id, "harbor gate") is True
    assert file_texts.term_matches(file_id, "rent is due") is False, "the older reader's text is not kept for search"


def test_a_newer_filter_is_built_again_from_the_kept_text_without_reading_files(files, monkeypatch: pytest.MonkeyPatch) -> None:
    ids = [_pdf_note("Lease.pdf", LEASE), create_file(original_filename="Story.rtf", mime_type="text/rtf", content_bytes=RTF, token=TOKEN).id]
    file_texts.refresh()
    read = _counting_reads(monkeypatch)
    monkeypatch.setattr(file_text_search_module, "FILTER_VERSION", FILTER_VERSION + 1)

    file_texts.refresh()

    assert read == []
    assert [_stored_versions(file_id)[1] for file_id in ids] == [FILTER_VERSION + 1] * 2
    assert file_texts.term_matches(ids[0], "rent is due") is True
    assert file_texts.term_matches(ids[1], "harbor gate") is True


def test_until_its_filter_is_built_again_a_file_is_found_by_its_text(files, monkeypatch: pytest.MonkeyPatch) -> None:
    # An older filter may say no where the newer one wouldn't: the text decides meanwhile.
    file_id = _pdf_note("Lease.pdf", LEASE)
    file_texts.refresh()
    monkeypatch.setattr(file_text_search_module, "filter_may_contain", lambda filter_bytes, core: False)
    monkeypatch.setattr(file_text_search_module, "FILTER_VERSION", FILTER_VERSION + 1)
    assert file_texts.term_matches(file_id, "rent is due") is True


def test_newer_versions_are_shown_as_reading_document_text(files, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("One.pdf", "Two.pdf"):
        _pdf_note(name, LEASE)
    file_texts.refresh()
    seen: list[list[dict[str, object]]] = []
    storage = file_texts._require_storage()
    file_texts.install_storage(replace(storage, store_text=lambda *args: (seen.append(background_work.snapshot()), storage.store_text(*args))))
    monkeypatch.setitem(TEXT_READER_VERSIONS, ".pdf", TEXT_READER_VERSIONS[".pdf"] + 1)
    try:
        file_texts.refresh()
    finally:
        file_texts.install_storage(storage)
    assert [[(entry["label"], entry["done"], entry["total"]) for entry in snapshot] for snapshot in seen] == [
        [("Reading document text", 0, 2)], [("Reading document text", 1, 2)],
    ]


# The throwaway restart, 2026-11-03: 15 files counted to 25. Logging in empties the loaded
# filters (a sensitive cache) while the reading runs, and the files read already looked unread.
def test_a_cache_cleared_while_reading_reads_no_file_twice(files, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("One.pdf", "Two.pdf", "Three.pdf"):
        _pdf_note(name, LEASE)
    read = _counting_reads(monkeypatch)
    real_keep = file_texts._keep

    def keep_then_clear(file_id: str, kept: KeptText) -> None:
        real_keep(file_id, kept)
        if len(read) == 1:
            file_texts.clear()

    monkeypatch.setattr(file_texts, "_keep", keep_then_clear)
    file_texts.refresh()
    assert sorted(read) == ["One.pdf", "Three.pdf", "Two.pdf"]


# --- Every file with text (docs/ready-to-build/files-shown-not-copied.md §2, acceptance check 31) --

PAGE = (
    b"<html><head><title>Head words</title><style>.harbor-style{}</style></head>"
    b"<body><script>var hidden = 'script words';</script><p>Lupus waited by the <b>harbor gate</b>.</p></body></html>"
)


@pytest.mark.parametrize(("name", "content"), [
    ("story.txt", b"\xef\xbb\xbfLupus waited by the harbor gate."),
    ("story.md", b"# Story\n\nLupus waited by the **harbor gate**."),
    ("story.py", b"print('Lupus waited by the harbor gate')\n"),
    ("story.csv", b"who,where\nLupus,harbor gate\n"),
    ("story.json", b'{"where": "harbor gate"}'),
    ("story.html", PAGE),
])
def test_a_quoted_search_finds_a_note_by_the_text_of_any_file_with_text(files, name: str, content: bytes) -> None:
    record = create_file(original_filename=name, mime_type="application/octet-stream", content_bytes=content, token=TOKEN)
    file_texts.refresh()
    index = _index({"story-note": f"![[{record.id}]]", "plain-note": "A note about groceries"})
    assert index.query_note_ids('"harbor gate"') == {"story-note"}


def test_a_web_pages_head_scripts_and_styles_are_no_text_of_it(files) -> None:
    record = create_file(original_filename="page.html", mime_type="text/html", content_bytes=PAGE, token=TOKEN)
    file_texts.refresh()
    assert file_texts.text_of(record.id) == "Lupus waited by the harbor gate ."
    for hidden in ("Head words", "script words", "harbor-style"):
        assert file_texts.term_matches(record.id, hidden) is False


def test_text_files_are_read_here_and_documents_in_their_own_process(files, monkeypatch: pytest.MonkeyPatch) -> None:
    # A PDF's or a document's parser can take long; plain text reads at once.
    calls: list[str] = []
    real_run = file_text_search_module.subprocess.run
    monkeypatch.setattr(file_text_search_module.subprocess, "run", lambda command, **options: calls.append(command[-1]) or real_run(command, **options))
    for name, content in (("a.txt", b"words"), ("b.html", PAGE), ("c.rtf", RTF)):
        create_file(original_filename=name, mime_type="application/octet-stream", content_bytes=content, token=TOKEN)
    file_texts.refresh()
    assert calls == [".rtf"]


# Find (Cmd+F) looked inside PDFs only, by their kind: an RTF's words were found by search and not
# by find (2026-11-03). It looks inside every file with text, as search does.
@pytest.mark.parametrize(("name", "content"), [("Story.rtf", RTF), ("story.txt", b"Lupus waited by the harbor gate.")])
def test_find_looks_inside_every_file_with_text(files, name: str, content: bytes) -> None:
    record = create_file(original_filename=name, mime_type="application/octet-stream", content_bytes=content, token=TOKEN)
    file_texts.refresh()
    note = SimpleNamespace(content=f"<div>![[{record.id}]]</div>")
    assert snapshot_module._files_holding_find_text(note, "harbor gate") == (record.id,)
