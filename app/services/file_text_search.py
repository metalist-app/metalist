"""A file's text, searchable without a note (docs/ready-to-build/folder-import-and-file-previews.md,
"Searchable file text"): a quoted search finds a note by a word in a PDF it shows.

Each file's text is extracted once and stored with the file, encrypted, beside a bloom filter of
its four-letter pieces (file_storage writes and reads them). At login only the filters are loaded;
a search reads a file's text only when its filter says the term may be there, so the results are
exactly those of reading every file's whole text. Text read for a search stays in a bounded cache,
emptied with every sensitive cache when the vault locks; so are the filters.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import PurePath
from threading import Lock, Thread
from typing import Callable, Dict, FrozenSet, List, Optional, Tuple


from app.security.sensitive_cache import SensitiveMemo, register_sensitive_cache, sensitive_caches_enabled
from app.services.auth_cache_state import on_cache_ready
from app.services import file_text_worker
from app.services.document_text import DOC_EXTENSION, DOCX_EXTENSION, RTF_EXTENSION
from app.services.file_view import PLAIN_TEXT_ENDINGS, WEB_PAGE_ENDINGS
from app.services.plain_text import file_text, web_page_text
from app.services.background_work import IMPORT_KEY, READING_PDF_TEXT_KEY, background_work
from app.services.text_terms import text_term_matches
from app.utils.byte_sizes import MIB

# A file's text stops here (about 2,000 pages; the maintainer, 2026-11-01): the cap only bounds
# what checking one file costs.
_MAX_FILE_TEXT_MIB = 5
MAX_FILE_TEXT_CHARACTERS = _MAX_FILE_TEXT_MIB * MIB
# The filter holds every piece of this many characters of the casefolded text: measured on 1 MB of
# English, a word the text lacks still looks possible 7% of the time (51% with 3, 1% with 5).
FILTER_PIECE_LENGTH = 4
# Bits per distinct piece and hash positions per piece: about 1% false "maybe" from the filter itself.
_FILTER_BITS_PER_PIECE = 10
_FILTER_HASH_COUNT = 7
_MIN_FILTER_BITS = 1024
_BITS_PER_BYTE = 8
_FILTER_HEADER_BYTES = 4
_BYTE_ORDER = "little"
# Two 4-byte halves of one digest make every hash position (double hashing).
_HASH_HALF_BYTES = 4
_HASH_DIGEST_BYTES = 8
_UTF8 = "utf-8"
# Halves of a character rejoined through UTF-16 (whole_characters).
_UTF16 = "utf-16-le"
_SURROGATE_PASS = "surrogatepass"
_REPLACE_UNREADABLE = "replace"
_WHITESPACE_RE = re.compile(r"\s+")
_PDF_SUFFIX = ".pdf"
# The version of the reader that keeps each kind's text, by ending: raise one when that reader
# changes what it keeps (a better way to read the kind, the cap, the whitespace or letters rule),
# and every file of the kind is read again (the maintainer, 2026-11-03). A kind added here is
# read for the first time the same way.
# RTF 2 (2026-11-03): a backslash ending a line is a paragraph break (TextEdit's), its words no
# longer run together. Text, Markdown, code, CSV, JSON and web pages (files-shown-not-copied.md
# §2, 2026-11-03): read as they are, a web page's visible text only.
_PLAIN_TEXT_READER_VERSION = 1
_WEB_PAGE_READER_VERSION = 1
TEXT_READER_VERSIONS = {
    # PDF 2: PDFium, with the spaces between words pypdf lost; RTF 3: its named characters
    # (\emdash, \rquote...) and page breaks, which joined words when skipped (2026-11-03).
    # .doc 1: Word 97-2003's text, read since 2026-11-03.
    _PDF_SUFFIX: 2, DOCX_EXTENSION: 1, RTF_EXTENSION: 3, DOC_EXTENSION: 1,
    **{ending: _PLAIN_TEXT_READER_VERSION for ending in PLAIN_TEXT_ENDINGS},
    **{ending: _WEB_PAGE_READER_VERSION for ending in WEB_PAGE_ENDINGS},
}
# Read in a process of their own at low priority (file_text_worker.py): a PDF's or a document's
# parser can take long; plain text and web pages are read in this one.
_WORKER_ENDINGS = frozenset({_PDF_SUFFIX, DOCX_EXTENSION, RTF_EXTENSION, DOC_EXTENSION})
# The version of the bloom filter (FILTER_PIECE_LENGTH, the bits per piece, the hashes): raise
# it when build_filter changes, and every filter is built again from the text already kept.
FILTER_VERSION = 1
# The work card: PDFs, Word documents and RTFs read for search.
READING_TEXT_LABEL = "Reading document text"
# Unicode's compatibility composition: a ligature glyph becomes its letters.
_LETTERS_FORM = "NFKC"
# Text read for searches, kept for the next ones (search-as-you-type, suggestions).
_TEXT_CACHE_FILES = 4096
_TEXT_CACHE_MIB = 64


@dataclass(frozen=True)
class ExtractedText:
    """A file's text as kept for search: whitespace collapsed, and whether it was cut at the cap.
    Empty when the file has none (a scan) or can't be read (damaged, locked)."""

    text: str
    is_cut: bool


@dataclass(frozen=True)
class StoredFileText:
    text: str
    is_cut: bool
    content_revision: int
    reader_version: int


@dataclass(frozen=True)
class StoredFilter:
    file_id: str
    filter_bytes: bytes
    is_cut: bool
    content_revision: int
    reader_version: int
    filter_version: int


@dataclass(frozen=True)
class KeptText:
    """A file's text and filter as stored, with the revision and versions that made them."""

    extracted: ExtractedText
    filter_bytes: bytes
    content_revision: int
    reader_version: int
    filter_version: int


@dataclass(frozen=True)
class FileTextStorage:
    """How the files database is reached (file_storage installs it: this module stays free of it)."""

    read_text: Callable[[str], Optional[StoredFileText]]
    read_filters: Callable[[], List[StoredFilter]]
    # (file id, content revision) of every stored file whose kind keeps its text.
    searchable_files: Callable[[], Dict[str, int]]
    # A file deleted meanwhile (a search's background read races deletions): None.
    read_file_bytes: Callable[[str], Optional[bytes]]
    file_name: Callable[[str], Optional[str]]
    store_text: Callable[[str, KeptText], None]


def is_searchable_file_name(file_name: str) -> bool:
    """A file whose text is kept for search: one with a reader for its ending
    (TEXT_READER_VERSIONS), the same rule for search, find and the reading."""
    return PurePath(file_name).suffix.casefold() in TEXT_READER_VERSIONS


def reader_version_of(file_name: str) -> int:
    """The version of the reader that keeps this file's text (TEXT_READER_VERSIONS)."""
    suffix = PurePath(file_name).suffix.casefold()
    if suffix not in TEXT_READER_VERSIONS:
        raise ValueError(f"no searchable text for {file_name!r}")
    return TEXT_READER_VERSIONS[suffix]


def extract_file_text(file_name: str, content: bytes) -> ExtractedText:
    """The text a file keeps for search, up to MAX_FILE_TEXT_CHARACTERS: a PDF's page after page,
    a document's (both read in a process of their own: file_text_worker.py), a text file's as it
    is, a web page's visible text. One that can't be read, or is locked, keeps no text and
    matches by name only."""
    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    if not is_searchable_file_name(file_name):
        raise ValueError(f"no searchable text for {file_name!r}")
    ending = PurePath(file_name).suffix.casefold()
    if ending in WEB_PAGE_ENDINGS:
        pages: Optional[List[str]] = [web_page_text(content)]
    elif ending in _WORKER_ENDINGS:
        pages = _file_pages(ending, content)
    else:
        pages = [file_text(content)]
    if pages is None:
        return ExtractedText(text="", is_cut=False)
    text = _WHITESPACE_RE.sub(" ", as_letters(whole_characters(" ".join(pages)))).strip()
    if len(text) <= MAX_FILE_TEXT_CHARACTERS:
        return ExtractedText(text=text, is_cut=False)
    return ExtractedText(text=text[:MAX_FILE_TEXT_CHARACTERS], is_cut=True)


def whole_characters(text: str) -> str:
    """Text whose every character is whole: a PDF's text can hold halves of a character (UTF-16
    surrogates); halves that belong together become their character, a lone one U+FFFD. A lone
    half can't be encoded, and building the filter of one PDF's text ended all reading there on
    every start (the maintainer's vault, 2026-11-03: 100 of 1,590 files read)."""
    return text.encode(_UTF16, _SURROGATE_PASS).decode(_UTF16, _REPLACE_UNREADABLE)


def as_letters(text: str) -> str:
    """Text as plain letters: a typeset PDF's ligature glyphs ("coe\ufb03cients") as the letters
    they join ("coefficients"), as search reads them, so the snippet and find's marks read them
    the same (NFKC; text kept before this was so is read through it, 2026-11-02)."""
    return unicodedata.normalize(_LETTERS_FORM, text)


def _file_pages(extension: str, content: bytes) -> Optional[List[str]]:
    """The file's text (a PDF's pages', read only until there is more than the cap; a Word
    document's or an RTF's whole), by a process of its own at low priority; None when it is
    locked or can't be read."""
    options: Dict[str, object] = {}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.BELOW_NORMAL_PRIORITY_CLASS
    completed = subprocess.run(
        [sys.executable, "-m", "app.services.file_text_worker", str(MAX_FILE_TEXT_CHARACTERS), extension],
        input=content, capture_output=True, check=True, **options,
    )
    answer = json.loads(completed.stdout)
    if file_text_worker.PAGES not in answer:
        return None
    pages = answer[file_text_worker.PAGES]
    assert isinstance(pages, list) and all(isinstance(page, str) for page in pages), "the file text worker answers pages of text"
    return pages


def build_filter(text_casefold: str) -> bytes:
    """A bloom filter of every FILTER_PIECE_LENGTH-character piece of the text: its size in bits,
    then the bits."""
    pieces = {text_casefold[index:index + FILTER_PIECE_LENGTH] for index in range(len(text_casefold) - FILTER_PIECE_LENGTH + 1)}
    bit_count = max(_MIN_FILTER_BITS, len(pieces) * _FILTER_BITS_PER_PIECE)
    bits = bytearray(-(-bit_count // _BITS_PER_BYTE))
    for piece in pieces:
        for position in _positions(piece, bit_count):
            bits[position // _BITS_PER_BYTE] |= 1 << (position % _BITS_PER_BYTE)
    return bit_count.to_bytes(_FILTER_HEADER_BYTES, _BYTE_ORDER) + bytes(bits)


def filter_may_contain(filter_bytes: bytes, core_casefold: str) -> bool:
    """False when the filtered text surely lacks core_casefold; True when it may hold it (and for
    a core shorter than a piece, which the filter can't tell)."""
    if len(core_casefold) < FILTER_PIECE_LENGTH:
        return True
    bit_count = int.from_bytes(filter_bytes[:_FILTER_HEADER_BYTES], _BYTE_ORDER)
    bits = filter_bytes[_FILTER_HEADER_BYTES:]
    for index in range(len(core_casefold) - FILTER_PIECE_LENGTH + 1):
        for position in _positions(core_casefold[index:index + FILTER_PIECE_LENGTH], bit_count):
            if not bits[position // _BITS_PER_BYTE] >> (position % _BITS_PER_BYTE) & 1:
                return False
    return True


def _positions(piece: str, bit_count: int) -> List[int]:
    digest = hashlib.blake2b(piece.encode(_UTF8), digest_size=_HASH_DIGEST_BYTES).digest()
    first = int.from_bytes(digest[:_HASH_HALF_BYTES], _BYTE_ORDER)
    second = int.from_bytes(digest[_HASH_HALF_BYTES:], _BYTE_ORDER)
    return [(first + round_index * second) % bit_count for round_index in range(_FILTER_HASH_COUNT)]


@dataclass(frozen=True)
class _LoadedFilter:
    filter_bytes: bytes
    is_cut: bool
    content_revision: int
    reader_version: int
    filter_version: int


# What a kept text needs: read again (no text yet, a changed file or a newer reader), or only its
# filter built again (a newer filter).
_READ = "read"
_FILTER = "filter"


class FileTexts:
    """The loaded filters, and the files' text read for searches."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._filters: Dict[str, _LoadedFilter] = {}
        # Whether _filters holds every stored filter: emptied (logging in empties every sensitive
        # cache), they load again when next asked for (_ensure_loaded).
        self._is_loaded = False
        self._storage: Optional[FileTextStorage] = None
        self._text_cache = SensitiveMemo(maxsize=_TEXT_CACHE_FILES, max_bytes=_TEXT_CACHE_MIB * MIB)
        self._worker: Optional[Thread] = None
        self._needs_another_pass = False
        # Called after file texts are added, so cached search results are recomputed.
        self._changed_listeners: List[Callable[[], None]] = []
        register_sensitive_cache(self.clear)

    def install_storage(self, storage: FileTextStorage) -> None:
        self._storage = storage

    def on_changed(self, listener: Callable[[], None]) -> None:
        self._changed_listeners.append(listener)

    def clear(self) -> None:
        with self._lock:
            self._filters.clear()
            self._is_loaded = False

    def loaded_file_ids(self) -> FrozenSet[str]:
        self._ensure_loaded()
        with self._lock:
            return frozenset(self._filters)

    def filter_bytes_total(self) -> int:
        self._ensure_loaded()
        with self._lock:
            return sum(len(loaded.filter_bytes) for loaded in self._filters.values())

    def is_cut(self, file_id: str) -> bool:
        self._ensure_loaded()
        with self._lock:
            return file_id in self._filters and self._filters[file_id].is_cut

    def term_matches(self, file_id: str, term: str) -> bool:
        """Whether the quoted search term is in the file's text (False for a file whose text
        isn't loaded yet: it matches by name only until then)."""
        self._ensure_loaded()
        with self._lock:
            if file_id not in self._filters:
                return False
            loaded = self._filters[file_id]
        # A filter of an older version may say no where the current one wouldn't: until it is
        # built again, the text itself decides.
        if loaded.filter_version == FILTER_VERSION and not filter_may_contain(loaded.filter_bytes, term.strip().casefold()):
            return False
        return text_term_matches(term, self._text_casefold(file_id, loaded))

    def text_of(self, file_id: str) -> str:
        """The file's stored text, as letters (for the snippet under its card)."""
        stored = self._require_storage().read_text(file_id)
        if stored is None:
            return ""
        return as_letters(stored.text)

    def _text_casefold(self, file_id: str, loaded: _LoadedFilter) -> str:
        # A newer reader's text replaces the older one's for the same revision.
        key = (file_id, loaded.content_revision, loaded.reader_version)
        found, value = self._text_cache.lookup(key)
        if found:
            return value
        stored = self._require_storage().read_text(file_id)
        text = ""
        if stored is not None and (stored.content_revision, stored.reader_version) == (loaded.content_revision, loaded.reader_version):
            text = as_letters(stored.text).casefold()
        self._text_cache.store(key, text)
        return text

    def _require_storage(self) -> FileTextStorage:
        if self._storage is None:
            raise RuntimeError("file_storage installs the file text storage at import")
        return self._storage

    def refresh(self) -> None:
        """Load the stored filters, then extract the text of every searchable file without it (or
        with an older revision's): once after login, and after a file arrives or changes."""
        storage = self._require_storage()
        if self._load_stored_filters(replaces_loaded=True):
            self._notify_changed()
        # Each file's text is kept as soon as it is read: a stop part way (a restart) goes on with
        # the files not read yet (the maintainer, 2026-11-02: a folder may hold 300 PDFs).
        pending = self._pending(storage)
        if not pending:
            return
        # Shown as it goes (background-work-cards.js); files arriving meanwhile join the count.
        with background_work.track(READING_PDF_TEXT_KEY, READING_TEXT_LABEL, total=len(pending)) as progress:
            # Logging in empties the loaded filters (a sensitive cache) while this runs: the
            # files handled already would look unread (15 files counted to 25, 2026-11-03).
            handled: set[str] = set()
            while pending:
                file_id, content_revision, need = pending[0]
                if need == _READ:
                    self.extract_and_store(file_id, content_revision)
                else:
                    self._rebuild_filter(file_id, content_revision)
                progress.advance()
                handled.add(file_id)
                pending = [entry for entry in self._pending(storage) if entry[0] not in handled]
                progress.set_total(len(handled) + len(pending))

    def _ensure_loaded(self) -> None:
        """Load the stored filters if they were emptied since. Logging in empties every sensitive
        cache, these too, after startup or the first login loaded them; nothing loaded them again,
        so no search or find saw a file's text until a file was added (the maintainer, 2026-11-03).
        A locked vault has none to load: its filters stay empty until it is unlocked."""
        with self._lock:
            if self._is_loaded:
                return
        if not sensitive_caches_enabled():
            return
        self._load_stored_filters(replaces_loaded=False)

    def _load_stored_filters(self, *, replaces_loaded: bool) -> bool:
        """Read every stored filter into memory; whether any was stored. refresh() replaces the
        loaded ones (it alone keeps texts, after this); loaded when asked, beside it, one it kept
        meanwhile (_keep) is newer than what was read, and stays."""
        stored_filters = self._require_storage().read_filters()
        with self._lock:
            for stored in stored_filters:
                if replaces_loaded or stored.file_id not in self._filters:
                    self._filters[stored.file_id] = _LoadedFilter(
                        stored.filter_bytes, stored.is_cut, stored.content_revision, stored.reader_version, stored.filter_version,
                    )
            self._is_loaded = True
        self._clear_if_locked()
        return len(stored_filters) > 0

    def _pending(self, storage: FileTextStorage) -> List[Tuple[str, int, str]]:
        """The searchable files whose text isn't kept yet, or is an older revision's or an older
        reader's (to read), or whose filter is an older version's (to build again)."""
        self._ensure_loaded()
        with self._lock:
            kept = dict(self._filters)
        pending: List[Tuple[str, int, str]] = []
        for file_id, content_revision in storage.searchable_files().items():
            file_name = storage.file_name(file_id)
            # Deleted meanwhile: nothing to keep.
            if file_name is None:
                continue
            if file_id not in kept or kept[file_id].content_revision != content_revision:
                pending.append((file_id, content_revision, _READ))
            elif kept[file_id].reader_version != reader_version_of(file_name):
                pending.append((file_id, content_revision, _READ))
            elif kept[file_id].filter_version != FILTER_VERSION:
                pending.append((file_id, content_revision, _FILTER))
        return pending

    def refresh_waiting_for_imports(self) -> None:
        """refresh() once no import runs: what the page shows (the imported notes, their images)
        comes before the PDFs' text, which changes nothing on it (the maintainer, 2026-11-02)."""
        background_work.wait_until_finished(IMPORT_KEY)
        self.refresh()

    def extract_and_store(self, file_id: str, content_revision: int) -> None:
        storage = self._require_storage()
        file_name = storage.file_name(file_id)
        content = storage.read_file_bytes(file_id)
        # Deleted meanwhile: nothing to keep.
        if file_name is None or content is None:
            return
        extracted = extract_file_text(file_name, content)
        self._keep(file_id, KeptText(
            extracted=extracted, filter_bytes=build_filter(extracted.text.casefold()), content_revision=content_revision,
            reader_version=reader_version_of(file_name), filter_version=FILTER_VERSION,
        ))

    def _rebuild_filter(self, file_id: str, content_revision: int) -> None:
        """A newer filter, built from the text already kept: the file isn't read again."""
        stored = self._require_storage().read_text(file_id)
        # Deleted, or changed meanwhile: the next pass reads it.
        if stored is None or stored.content_revision != content_revision:
            return
        text = as_letters(stored.text)
        self._keep(file_id, KeptText(
            extracted=ExtractedText(text=text, is_cut=stored.is_cut), filter_bytes=build_filter(text.casefold()),
            content_revision=content_revision, reader_version=stored.reader_version, filter_version=FILTER_VERSION,
        ))

    def _keep(self, file_id: str, kept: KeptText) -> None:
        self._require_storage().store_text(file_id, kept)
        with self._lock:
            self._filters[file_id] = _LoadedFilter(
                kept.filter_bytes, kept.extracted.is_cut, kept.content_revision, kept.reader_version, kept.filter_version,
            )
        self._clear_if_locked()
        self._notify_changed()

    def _clear_if_locked(self) -> None:
        # The vault locked while filters were added: they must not outlive it.
        if not sensitive_caches_enabled():
            self.clear()

    def refresh_in_background(self) -> None:
        """refresh() on a thread of its own; a call while one runs makes it go round once more."""
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                self._needs_another_pass = True
                return
            self._worker = Thread(target=self._refresh_until_settled, name="metalist-file-texts", daemon=True)
            self._worker.start()

    def wait_for_background(self) -> None:
        with self._lock:
            worker = self._worker
        if worker is not None:
            worker.join()

    def _refresh_until_settled(self) -> None:
        while True:
            self.refresh_waiting_for_imports()
            with self._lock:
                if not self._needs_another_pass:
                    return
                self._needs_another_pass = False

    def _notify_changed(self) -> None:
        for listener in list(self._changed_listeners):
            listener()


file_texts = FileTexts()
# After login (and unlock): the filters, then any file text still missing, beside the requests.
on_cache_ready(file_texts.refresh_in_background)
