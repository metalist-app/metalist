"""A file's text kept for search, read in a process of its own (python -m
app.services.file_text_worker MAX_CHARACTERS EXTENSION, the file on stdin, JSON on stdout): a
PDF's (PDFium, through pypdfium2), a Word document's or an RTF's (document_text.py). Reading a
PDF in the server's process starved every request while it ran (15 MB of PDFs kept a 4 KB
image waiting 10 to 15 seconds, 2026-11-02). Here it runs at low priority, and the server only
waits for its answer. It imports PDFium and the document reader, not the rest of MetaList.

A PDF's words: pypdf read some PDFs without the spaces between them
("Adolescentdrivershavethehighestrate", the maintainer's vault, 2026-11-03). PDFium puts most
back from where the words sit; on some lines it doesn't, and there the gaps between the
letters' boxes say where they are (line_with_gap_spaces). Each page keeps the reading of the
two with less trouble: fewer words run together and letters standing apart (reading_trouble).
Measured on 300 of the maintainer's PDFs: 62 words run together against pypdf's 717 and
PDFium's own 81, and no more letters apart than PDFium's own."""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
from contextlib import closing
from typing import Dict, List, NamedTuple, Sequence

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw

from app.services.document_text import DOCUMENT_EXTENSIONS, UnreadableDocument, document_text
from app.services.exception_capture import CapturedExceptionContext

# Below everything visible: the server's requests, images.
_LOW_PRIORITY = 10
# The module name, MAX_CHARACTERS and the file's EXTENSION.
_EXPECTED_ARGV_LENGTH = 3
PDF_EXTENSION = ".pdf"

LOCKED = "locked"
UNREADABLE = "unreadable"
PAGES = "pages"

# A gap between two letters on a line is a space when it is wider than the line's usual gap by
# this much of the font size (a word space is about a quarter to a third of it).
_SPACE_GAP_EM = 0.3
# The gaps tell where words are only on a line whose letters touch (its usual gap under this
# much of the font size): letter-spaced headings, and boxes narrower than their letters (some
# data sheets), would be split letter by letter.
_TOUCHING_EM = 0.05
# A run of this many letters is words run together: few words are as long.
_RUN_TOGETHER_LETTERS = 20
_STRAY_LETTERS_AT_MOST = 2
# One and two letter words, which are no letters standing apart.
_SHORT_WORDS = frozenset(
    "a i an as at be by do go he if in is it me my no of oh ok on or so to up us we am id vs et al".split(),
)
_LETTERS_RE = re.compile(r"[A-Za-z]+")
_LOWERCASE_RE = re.compile(r"[a-z]+")
_LINE_BREAKS = frozenset("\r\n")
# PDFium's code for a character it has no Unicode for.
_NO_UNICODE = 0


class Glyph(NamedTuple):
    """One character PDFium drew: its text and its box (the letter's width, not its ink)."""

    char: str
    left: float
    right: float
    bottom: float
    top: float
    size: float


def read_pages(content: bytes, max_characters: int) -> Dict[str, object]:
    """{pages: [...]} read only until there is more than max_characters; {locked: true} for a
    PDF behind a password; {unreadable: true} for one PDFium can't read (the user's file: it
    keeps no text and matches by name only)."""
    capture = CapturedExceptionContext(pdfium.PdfiumError, ValueError, boundary='app/services/file_text_worker.py:read_pages:pdf_capture')
    answer: Dict[str, object] = {UNREADABLE: True}
    with capture:
        answer = _read(content, max_characters)
    error = capture.captured_exception
    if error is None:
        return answer
    if isinstance(error, pdfium.PdfiumError) and error.err_code == pdfium_raw.FPDF_ERR_PASSWORD:
        return {LOCKED: True}
    return {UNREADABLE: True}


def _read(content: bytes, max_characters: int) -> Dict[str, object]:
    pages: List[str] = []
    length = 0
    with closing(pdfium.PdfDocument(content)) as document:
        for page_index in range(len(document)):
            with closing(document[page_index]) as page:
                page_text = _page_text(page)
            pages.append(page_text)
            length += len(page_text)
            if length > max_characters:
                break
    return {PAGES: pages}


def _page_text(page: pdfium.PdfPage) -> str:
    """The page's text: PDFium's own, or with the spaces the letters' gaps show, whichever
    reads with less trouble (PDFium's own on a tie)."""
    with closing(page.get_textpage()) as textpage:
        # Every character, as pypdf read them: text outside the page's box is the file's too.
        own = textpage.get_text_range()
        spaced = _text_with_gap_spaces(textpage)
    if reading_trouble(spaced) < reading_trouble(own):
        return spaced
    return own


def _text_with_gap_spaces(textpage: pdfium.PdfTextPage) -> str:
    """PDFium's characters in order, each line with spaces where its letters' gaps show them."""
    box = pdfium_raw.FS_RECTF()
    parts: List[str] = []
    line: List[Glyph] = []
    for index in range(textpage.count_chars()):
        code = pdfium_raw.FPDFText_GetUnicode(textpage, index)
        if code == _NO_UNICODE:
            continue
        char = chr(code)
        if char in _LINE_BREAKS:
            parts.append(line_with_gap_spaces(line))
            parts.append(char)
            line = []
            continue
        if not pdfium_raw.FPDFText_GetLooseCharBox(textpage, index, box):
            raise ValueError(f"PDFium gave no box for character {index}")
        line.append(Glyph(char, box.left, box.right, box.bottom, box.top, pdfium_raw.FPDFText_GetFontSize(textpage, index)))
    parts.append(line_with_gap_spaces(line))
    return "".join(parts)


def _are_neighbours(first: Glyph, second: Glyph) -> bool:
    """Two letters side by side on one line (spaces, and letters on lines apart, are not)."""
    if first.char.isspace() or second.char.isspace():
        return False
    return min(first.top, second.top) - max(first.bottom, second.bottom) > 0


def line_with_gap_spaces(glyphs: Sequence[Glyph]) -> str:
    """A line's text with a space wherever two letters stand further apart than the line's
    letters usually do, by _SPACE_GAP_EM of the font size; as it is on a line whose letters
    don't touch (_TOUCHING_EM), whose gaps tell nothing."""
    text = "".join(glyph.char for glyph in glyphs)
    gaps = [second.left - first.right for first, second in zip(glyphs, glyphs[1:]) if _are_neighbours(first, second)]
    if not gaps:
        return text
    usual = statistics.median(gaps)
    size = statistics.median(glyph.size for glyph in glyphs if not glyph.char.isspace())
    if abs(usual) >= _TOUCHING_EM * size:
        return text
    parts = [glyphs[0].char]
    for first, second in zip(glyphs, glyphs[1:]):
        if _are_neighbours(first, second) and second.left - first.right - usual > _SPACE_GAP_EM * max(first.size, second.size):
            parts.append(" ")
        parts.append(second.char)
    return "".join(parts)


def reading_trouble(text: str) -> int:
    """How much of a reading of a page looks wrong: runs of letters as long as words run
    together, and one or two letters standing apart that are no short word."""
    run_together = sum(1 for word in _LETTERS_RE.findall(text) if len(word) >= _RUN_TOGETHER_LETTERS)
    stray = sum(1 for word in _LOWERCASE_RE.findall(text) if len(word) <= _STRAY_LETTERS_AT_MOST and word not in _SHORT_WORDS)
    return run_together + stray


def read_document(extension: str, content: bytes, max_characters: int) -> Dict[str, object]:
    """A Word document's or an RTF's text as one page, cut past max_characters;
    {unreadable: true} for one that can't be read (the user's file: by name only)."""
    capture = CapturedExceptionContext(UnreadableDocument, boundary='app/services/file_text_worker.py:read_document:document_capture')
    text = ""
    with capture:
        text = document_text(f"document{extension}", content)
    if capture.captured_exception is not None:
        return {UNREADABLE: True}
    return {PAGES: [text[:max_characters + 1]]}


def read_file_text(extension: str, content: bytes, max_characters: int) -> Dict[str, object]:
    if extension == PDF_EXTENSION:
        return read_pages(content, max_characters)
    if extension in DOCUMENT_EXTENSIONS:
        return read_document(extension, content, max_characters)
    raise ValueError(f"no text kept for a {extension!r} file")


def main() -> None:
    if len(sys.argv) != _EXPECTED_ARGV_LENGTH:
        raise SystemExit("usage: python -m app.services.file_text_worker MAX_CHARACTERS EXTENSION")
    if hasattr(os, "nice"):
        os.nice(_LOW_PRIORITY)
    answer = read_file_text(sys.argv[2], sys.stdin.buffer.read(), int(sys.argv[1]))
    sys.stdout.write(json.dumps(answer))


if __name__ == "__main__":
    main()
