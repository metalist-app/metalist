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
import re
import unicodedata
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from threading import Lock, Thread
from typing import Callable, Dict, FrozenSet, List, Optional

from pypdf import PasswordType, PdfReader
from pypdf.errors import PyPdfError

from app.security.sensitive_cache import SensitiveMemo, register_sensitive_cache, sensitive_caches_enabled
from app.services.auth_cache_state import on_cache_ready
from app.services.exception_capture import CapturedExceptionContext
from app.services.text_terms import text_term_matches
from app.utils.byte_sizes import MIB

# The file kinds whose text is kept for search (file_storage's thumbnail kinds).
SEARCHABLE_FILE_KINDS = frozenset({"pdf"})
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
_WHITESPACE_RE = re.compile(r"\s+")
_PDF_SUFFIX = ".pdf"
_NO_PASSWORD = ""
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


@dataclass(frozen=True)
class StoredFilter:
    file_id: str
    filter_bytes: bytes
    is_cut: bool
    content_revision: int


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
    store_text: Callable[[str, ExtractedText, bytes, int], None]


def is_searchable_file_name(file_name: str) -> bool:
    return PurePath(file_name).suffix.casefold() == _PDF_SUFFIX


def extract_file_text(file_name: str, content: bytes) -> ExtractedText:
    """The text a file keeps for search: a PDF's, page after page, up to MAX_FILE_TEXT_CHARACTERS."""
    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    if not is_searchable_file_name(file_name):
        raise ValueError(f"no searchable text for {file_name!r}")
    # The user's file: one pypdf can't read keeps no text and matches by name only.
    pdf_capture = CapturedExceptionContext(
        PyPdfError,
        ValueError,
        boundary='app/services/file_text_search.py:extract_file_text:pdf_capture',
    )
    pages: Optional[List[str]] = None
    with pdf_capture:
        pages = _pdf_pages(content)
    if pdf_capture.captured_exception is not None or pages is None:
        return ExtractedText(text="", is_cut=False)
    text = _WHITESPACE_RE.sub(" ", as_letters(" ".join(pages))).strip()
    if len(text) <= MAX_FILE_TEXT_CHARACTERS:
        return ExtractedText(text=text, is_cut=False)
    return ExtractedText(text=text[:MAX_FILE_TEXT_CHARACTERS], is_cut=True)


def as_letters(text: str) -> str:
    """Text as plain letters: a typeset PDF's ligature glyphs ("coe\ufb03cients") as the letters
    they join ("coefficients"), as search reads them, so the snippet and find's marks read them
    the same (NFKC; text kept before this was so is read through it, 2026-11-02)."""
    return unicodedata.normalize(_LETTERS_FORM, text)


def _pdf_pages(content: bytes) -> Optional[List[str]]:
    """The PDF's pages' text, read only until there is more than the cap; None when it is locked."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted and reader.decrypt(_NO_PASSWORD) == PasswordType.NOT_DECRYPTED:
            return None
        pages: List[str] = []
        length = 0
        for page in reader.pages:
            page_text = page.extract_text()
            pages.append(page_text)
            length += len(page_text)
            if length > MAX_FILE_TEXT_CHARACTERS:
                break
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


class FileTexts:
    """The loaded filters, and the files' text read for searches."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._filters: Dict[str, _LoadedFilter] = {}
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

    def loaded_file_ids(self) -> FrozenSet[str]:
        with self._lock:
            return frozenset(self._filters)

    def filter_bytes_total(self) -> int:
        with self._lock:
            return sum(len(loaded.filter_bytes) for loaded in self._filters.values())

    def is_cut(self, file_id: str) -> bool:
        with self._lock:
            return file_id in self._filters and self._filters[file_id].is_cut

    def term_matches(self, file_id: str, term: str) -> bool:
        """Whether the quoted search term is in the file's text (False for a file whose text
        isn't loaded yet: it matches by name only until then)."""
        with self._lock:
            if file_id not in self._filters:
                return False
            loaded = self._filters[file_id]
        if not filter_may_contain(loaded.filter_bytes, term.strip().casefold()):
            return False
        return text_term_matches(term, self._text_casefold(file_id, loaded.content_revision))

    def text_of(self, file_id: str) -> str:
        """The file's stored text, as letters (for the snippet under its card)."""
        stored = self._require_storage().read_text(file_id)
        if stored is None:
            return ""
        return as_letters(stored.text)

    def _text_casefold(self, file_id: str, content_revision: int) -> str:
        key = (file_id, content_revision)
        found, value = self._text_cache.lookup(key)
        if found:
            return value
        stored = self._require_storage().read_text(file_id)
        text = ""
        if stored is not None and stored.content_revision == content_revision:
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
        loaded = {stored.file_id: stored for stored in storage.read_filters()}
        with self._lock:
            for stored in loaded.values():
                self._filters[stored.file_id] = _LoadedFilter(stored.filter_bytes, stored.is_cut, stored.content_revision)
        self._clear_if_locked()
        if loaded:
            self._notify_changed()
        for file_id, content_revision in storage.searchable_files().items():
            if file_id in loaded and loaded[file_id].content_revision == content_revision:
                continue
            self.extract_and_store(file_id, content_revision)

    def extract_and_store(self, file_id: str, content_revision: int) -> None:
        storage = self._require_storage()
        file_name = storage.file_name(file_id)
        content = storage.read_file_bytes(file_id)
        # Deleted meanwhile: nothing to keep.
        if file_name is None or content is None:
            return
        extracted = extract_file_text(file_name, content)
        filter_bytes = build_filter(extracted.text.casefold())
        storage.store_text(file_id, extracted, filter_bytes, content_revision)
        with self._lock:
            self._filters[file_id] = _LoadedFilter(filter_bytes, extracted.is_cut, content_revision)
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
            self.refresh()
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
