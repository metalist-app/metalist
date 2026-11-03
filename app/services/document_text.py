"""Word (.docx, and Word 97-2003's .doc) and RTF documents, read with Python alone (the maintainer, 2026-11-02: MetaList's
own reader, no new dependency): as note HTML for the preview note a dropped or imported one
gets (headings, bold, italics, lists, tables), and as text kept with the file for search
(folder-import-and-file-previews.md §5). Imports nothing of MetaList: the file text worker
runs it in a process of its own.

A .docx is a zip holding word/document.xml; an RTF is text with control words; a .doc is an OLE
file (opened with olefile) whose WordDocument stream holds the text in pieces a table lists.
What can't be read raises UnreadableDocument: the user's file keeps its card and matches by
name only."""

from __future__ import annotations

import bisect
import html
import re
import struct
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from typing import Callable, Dict, List, Tuple
from xml.etree import ElementTree

import olefile

from app.services.document_highlights import HIGHLIGHT_CLASS_PREFIX, NO_HIGHLIGHT, highlight_of_colour, highlight_of_number
from app.services.exception_capture import CapturedExceptionContext

DOCX_EXTENSION = ".docx"
RTF_EXTENSION = ".rtf"
DOC_EXTENSION = ".doc"
DOCUMENT_EXTENSIONS = frozenset({DOCX_EXTENSION, RTF_EXTENSION, DOC_EXTENSION})

# A document whose text part unpacks larger than this isn't read (a zip can unpack huge).
_MAX_DOCUMENT_XML_BYTES = 64 * 1024 * 1024
_DOCUMENT_PART = "word/document.xml"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_HEADING_STYLE_RE = re.compile(r"^(?:heading|berschrift|titre)\s*([1-6])$", re.IGNORECASE)
_TITLE_STYLE = "title"
_FALSE_VALUES = frozenset({"0", "false", "off"})
_DOCTYPE_MARK = b"<!DOCTYPE"
# A whole .docx (its pictures too) unpacking past this isn't handed to the preview's reader.
_MAX_DOCX_UNPACKED_BYTES = 256 * 1024 * 1024
_XML_PART_ENDINGS = (".xml", ".rels")


class UnreadableDocument(ValueError):
    """The user's document can't be read: it keeps its card, matching by name only."""


@dataclass(frozen=True)
class _Look:
    """How a run of text is set: what the viewer shows of a document's style (2026-11-03)."""

    is_bold: bool
    is_italic: bool
    is_underline: bool
    is_strike: bool
    # One of Word's 16 (document_highlights.py), or NO_HIGHLIGHT.
    highlight: str


_PLAIN = _Look(is_bold=False, is_italic=False, is_underline=False, is_strike=False, highlight=NO_HIGHLIGHT)


@dataclass(frozen=True)
class _Run:
    text: str
    look: _Look
    # A line break inside the paragraph.
    is_break: bool


@dataclass(frozen=True)
class _Block:
    """A paragraph (its tag: p, h1..h6, li) or a table (rows of cells' text)."""

    tag: str
    runs: Tuple[_Run, ...]
    rows: Tuple[Tuple[str, ...], ...]


def document_html(file_name: str, content: bytes) -> str:
    """The document as note HTML (still to be sanitized as a note's)."""
    return _blocks_html(_blocks(file_name, content))


def document_text(file_name: str, content: bytes) -> str:
    """The document's text: a line per paragraph and table row (cells with tabs)."""
    lines: List[str] = []
    for block in _blocks(file_name, content):
        if block.tag == "table":
            lines.extend("\t".join(row) for row in block.rows)
            continue
        lines.extend("".join(_run_text(run) for run in block.runs).split("\n"))
    return "\n".join(line for line in lines if line.strip() != "")


def _run_text(run: _Run) -> str:
    if run.is_break:
        return "\n"
    return run.text


def _blocks(file_name: str, content: bytes) -> List[_Block]:
    extension = PurePath(file_name).suffix.lower()
    readers: Dict[str, Callable[[bytes], List[_Block]]] = {
        DOCX_EXTENSION: _docx_blocks, RTF_EXTENSION: _rtf_blocks, DOC_EXTENSION: _doc_blocks,
    }
    if extension not in readers:
        raise ValueError(f"not a Word or RTF document: {file_name!r}")
    return readers[extension](content)


# --- Word -------------------------------------------------------------------------------


def _docx_xml(content: bytes) -> bytes:
    if not zipfile.is_zipfile(BytesIO(content)):
        raise UnreadableDocument("not a Word document")
    # The user's file: a damaged zip is a document that can't be read.
    capture = CapturedExceptionContext(zipfile.BadZipFile, boundary='app/services/document_text.py:_docx_xml:zip_capture')
    xml = b""
    with capture:
        xml = _document_part(content)
    if capture.captured_exception is not None:
        raise UnreadableDocument("a damaged Word document") from capture.captured_exception
    # Word writes no DTD: one could only be there to expand entities without end.
    if _DOCTYPE_MARK in xml:
        raise UnreadableDocument("a Word document with a DTD")
    return xml


def require_safe_docx(content: bytes) -> None:
    """Raise UnreadableDocument unless the .docx is a zip whose parts are safe to hand to another
    reader (mammoth, for the preview): its text part there, no part unpacking past the cap, and
    no XML part with a DTD (Word writes none: one could only expand entities without end)."""
    if not zipfile.is_zipfile(BytesIO(content)):
        raise UnreadableDocument("not a Word document")
    capture = CapturedExceptionContext(zipfile.BadZipFile, boundary='app/services/document_text.py:require_safe_docx:zip_capture')
    with capture:
        _require_safe_parts(content)
    if capture.captured_exception is not None:
        raise UnreadableDocument("a damaged Word document") from capture.captured_exception


def _require_safe_parts(content: bytes) -> None:
    with zipfile.ZipFile(BytesIO(content)) as archive:
        if _DOCUMENT_PART not in archive.namelist():
            raise UnreadableDocument("a Word document without its text")
        if sum(info.file_size for info in archive.infolist()) > _MAX_DOCX_UNPACKED_BYTES:
            raise UnreadableDocument("a Word document too large to read")
        for info in archive.infolist():
            if info.filename.endswith(_XML_PART_ENDINGS) and _DOCTYPE_MARK in archive.read(info):
                raise UnreadableDocument("a Word document with a DTD")


def _document_part(content: bytes) -> bytes:
    with zipfile.ZipFile(BytesIO(content)) as archive:
        if _DOCUMENT_PART not in archive.namelist():
            raise UnreadableDocument("a Word document without its text")
        if archive.getinfo(_DOCUMENT_PART).file_size > _MAX_DOCUMENT_XML_BYTES:
            raise UnreadableDocument("a Word document too large to read")
        return archive.read(_DOCUMENT_PART)


def _docx_root(content: bytes) -> ElementTree.Element:
    xml = _docx_xml(content)
    capture = CapturedExceptionContext(ElementTree.ParseError, boundary='app/services/document_text.py:_docx_root:xml_capture')
    root = None
    with capture:
        root = ElementTree.fromstring(xml)
    if capture.captured_exception is not None or root is None:
        raise UnreadableDocument("a Word document whose text can't be read")
    return root


def _docx_blocks(content: bytes) -> List[_Block]:
    root = _docx_root(content)
    body = root.find(f"{_W}body")
    if body is None:
        raise UnreadableDocument("a Word document without a body")
    blocks: List[_Block] = []
    for child in body:
        if child.tag == f"{_W}p":
            blocks.append(_Block(tag=_docx_paragraph_tag(child), runs=tuple(_docx_runs(child)), rows=()))
        elif child.tag == f"{_W}tbl":
            blocks.append(_Block(tag="table", runs=(), rows=tuple(_docx_rows(child))))
    return blocks


def _docx_paragraph_tag(paragraph: ElementTree.Element) -> str:
    properties = paragraph.find(f"{_W}pPr")
    if properties is None:
        return "p"
    if properties.find(f"{_W}numPr") is not None:
        return "li"
    style = properties.find(f"{_W}pStyle")
    if style is None:
        return "p"
    name = style.get(f"{_W}val")
    if name is None:
        return "p"
    if name.casefold() == _TITLE_STYLE:
        return "h1"
    heading = _HEADING_STYLE_RE.match(name)
    if heading is not None:
        return f"h{heading.group(1)}"
    return "p"


def _is_on(properties: ElementTree.Element | None, tag: str) -> bool:
    if properties is None:
        return False
    element = properties.find(f"{_W}{tag}")
    if element is None:
        return False
    # <w:b/> alone is on; w:val="0" (or false, off) turns it off.
    value = element.get(f"{_W}val")
    if value is None:
        return True
    return value.casefold() not in _FALSE_VALUES


def _docx_runs(paragraph: ElementTree.Element) -> List[_Run]:
    runs: List[_Run] = []
    for run in paragraph.iter(f"{_W}r"):
        properties = run.find(f"{_W}rPr")
        # The viewer reads a .docx through mammoth: this reading is its text, bold and italics.
        look = _Look(
            is_bold=_is_on(properties, "b"), is_italic=_is_on(properties, "i"), is_underline=False, is_strike=False,
            highlight=NO_HIGHLIGHT,
        )
        for piece in run:
            if piece.tag == f"{_W}t" and piece.text is not None:
                runs.append(_Run(text=piece.text, look=look, is_break=False))
            elif piece.tag == f"{_W}tab":
                runs.append(_Run(text="\t", look=look, is_break=False))
            elif piece.tag in (f"{_W}br", f"{_W}cr"):
                runs.append(_Run(text="", look=_PLAIN, is_break=True))
    return runs


def _docx_rows(table: ElementTree.Element) -> List[Tuple[str, ...]]:
    rows: List[Tuple[str, ...]] = []
    for row in table.findall(f"{_W}tr"):
        cells = []
        for cell in row.findall(f"{_W}tc"):
            paragraphs = ["".join(run.text for run in _docx_runs(paragraph)) for paragraph in cell.findall(f"{_W}p")]
            cells.append(" ".join(text for text in paragraphs if text != ""))
        rows.append(tuple(cells))
    return rows


# --- RTF --------------------------------------------------------------------------------

_RTF_START = b"{\\rtf"
_CONTROL_RE = re.compile(rb"\\([a-zA-Z]{1,32})(-?\d{1,10})? ?|\\'([0-9a-fA-F]{2})|\\(.)|([{}])|([^\\{}\r\n]+)|[\r\n]+", re.DOTALL)
# Groups holding no text of the document: font and colour tables, styles, its information,
# pictures, objects, fields' instructions and the like.
_SKIPPED_DESTINATIONS = frozenset({
    "fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "fldinst", "listtable", "listoverridetable",
    "themedata", "datastore", "latentstyles", "rsidtbl", "generator", "xmlnstbl", "mmathPr", "header", "footer",
    "headerl", "headerr", "footerl", "footerr", "footnote", "bkmkstart", "bkmkend", "filetbl", "revtbl", "pgdsctbl",
})
_DEFAULT_CODE_PAGE = "cp1252"
_UNICODE_SIGNED_BASE = 65536
_LINE_ENDS = frozenset({"\n", "\r"})
_SYMBOLS = {"~": "\u00a0", "-": "", "_": "\u2011", "\\": "\\", "{": "{", "}": "}"}
# Characters RTF names with a control word. Skipped, they joined the words around them
# ("450,000 babiesthat's", page ranges "521534": the maintainer's RTFs, 2026-11-03).
_NAMED_CHARACTERS = {
    "emdash": "\u2014", "endash": "\u2013", "lquote": "\u2018", "rquote": "\u2019", "ldblquote": "\u201c",
    "rdblquote": "\u201d", "bullet": "\u2022", "emspace": "\u2003", "enspace": "\u2002", "qmspace": "\u2005",
}
# Words ending a paragraph: a paragraph's, a section's, a table row's, a page's and a column's.
_PARAGRAPH_ENDS = frozenset({"par", "sect", "row", "page", "column"})
# Underline's words: on (\ul, and each kind of line), off (\ulnone, \ul0); \ulc is its colour.
_UNDERLINE_WORDS = frozenset({
    "ul", "uld", "uldash", "uldashd", "uldashdd", "uldb", "ulhwave", "ulldash", "ulth", "ulthd", "ulthdash",
    "ulthdashd", "ulthdashdd", "ulthldash", "ululdbwave", "ulw", "ulwave", "ulhair",
})
_UNDERLINE_OFF = "ulnone"
_STRIKE_WORDS = frozenset({"strike", "striked"})
# A highlight as Word writes it (\highlightN), a background as TextEdit does (\cbN, \chcbpatN):
# a colour of the colour table, 0 for none. White is no background (TextEdit's \cb1 ends one).
_HIGHLIGHT_WORD = "highlight"
_BACKGROUND_WORDS = frozenset({"cb", "chcbpat"})
_COLOUR_TABLE = "colortbl"
_COLOUR_PARTS = ("red", "green", "blue")
_COLOUR_END = ";"
_WHITE = (255, 255, 255)


@dataclass
class _RtfState:
    is_bold: bool
    is_italic: bool
    is_underline: bool
    is_strike: bool
    highlight: str
    is_skipped: bool
    is_colour_table: bool
    # Characters to skip after a \u (\ucN), the alternative a reader without Unicode shows.
    unicode_skip: int


def _rtf_blocks(content: bytes) -> List[_Block]:
    if not content.lstrip().startswith(_RTF_START):
        raise UnreadableDocument("not an RTF document")
    code_page = _DEFAULT_CODE_PAGE
    stack: List[_RtfState] = []
    state = _RtfState(
        is_bold=False, is_italic=False, is_underline=False, is_strike=False, highlight=NO_HIGHLIGHT, is_skipped=False,
        is_colour_table=False, unicode_skip=1,
    )
    blocks: List[_Block] = []
    runs: List[_Run] = []
    pending_skip = 0
    is_starred = False
    # The colour table's colours by number (0, before its first ";", is the default: none).
    colours: List[Tuple[int, ...] | None] = []
    # The colour being read: a part left out is 0; one with no part at all is the default.
    colour = [0] * len(_COLOUR_PARTS)
    has_colour_part = False

    def add(text: str) -> None:
        if not state.is_skipped and text != "":
            look = _Look(
                is_bold=state.is_bold, is_italic=state.is_italic, is_underline=state.is_underline,
                is_strike=state.is_strike, highlight=state.highlight,
            )
            runs.append(_Run(text=text, look=look, is_break=False))

    def highlight_of(number: int | None, is_background: bool) -> str:
        if number is None or not 0 < number < len(colours) or colours[number] is None:
            return NO_HIGHLIGHT
        colour = colours[number]
        assert colour is not None
        if is_background and colour == _WHITE:
            return NO_HIGHLIGHT
        return highlight_of_colour(colour)

    def end_paragraph() -> None:
        blocks.append(_Block(tag="p", runs=tuple(runs), rows=()))
        runs.clear()

    for match in _CONTROL_RE.finditer(content):
        word, parameter, hex_byte, symbol, brace, text = match.groups()
        if pending_skip > 0 and (hex_byte is not None or text is not None or symbol is not None):
            if text is not None and len(text) > pending_skip:
                text = text[pending_skip:]
                pending_skip = 0
            else:
                if text is None:
                    pending_skip -= 1
                else:
                    pending_skip -= len(text)
                continue
        if brace == b"{":
            stack.append(state)
            state = _RtfState(
                state.is_bold, state.is_italic, state.is_underline, state.is_strike, state.highlight, state.is_skipped,
                state.is_colour_table, state.unicode_skip,
            )
            is_starred = False
        elif brace == b"}":
            if not stack:
                break
            state = stack.pop()
        elif symbol is not None:
            character = symbol.decode("latin-1")
            if character == "*":
                is_starred = True
            # A backslash ending a line is \par (TextEdit ends every line so).
            elif character in _LINE_ENDS:
                if not state.is_skipped:
                    end_paragraph()
            elif character in _SYMBOLS:
                add(_SYMBOLS[character])
        elif hex_byte is not None:
            add(bytes([int(hex_byte, 16)]).decode(code_page, errors="replace"))
        elif word is not None:
            name = word.decode("ascii")
            value = None
            if parameter is not None:
                value = int(parameter)
            if is_starred or name in _SKIPPED_DESTINATIONS:
                state.is_skipped = True
                is_starred = False
            if name == _COLOUR_TABLE:
                state.is_colour_table = True
            if state.is_colour_table and name in _COLOUR_PARTS and value is not None:
                colour[_COLOUR_PARTS.index(name)] = value
                has_colour_part = True
            if name == "ansicpg" and value is not None:
                code_page = f"cp{value}"
            elif name in _PARAGRAPH_ENDS:
                if not state.is_skipped:
                    end_paragraph()
            elif name in _NAMED_CHARACTERS:
                add(_NAMED_CHARACTERS[name])
            elif name == "line":
                if not state.is_skipped:
                    runs.append(_Run(text="", look=_PLAIN, is_break=True))
            elif name == "tab" or name == "cell":
                add("\t")
            elif name == "b":
                state.is_bold = value != 0
            elif name == "i":
                state.is_italic = value != 0
            elif name == "plain":
                state.is_bold, state.is_italic, state.is_underline, state.is_strike = False, False, False, False
                state.highlight = NO_HIGHLIGHT
            elif name in _UNDERLINE_WORDS:
                state.is_underline = value != 0
            elif name == _UNDERLINE_OFF:
                state.is_underline = False
            elif name in _STRIKE_WORDS:
                state.is_strike = value != 0
            elif name == _HIGHLIGHT_WORD:
                state.highlight = highlight_of(value, is_background=False)
            elif name in _BACKGROUND_WORDS:
                state.highlight = highlight_of(value, is_background=True)
            elif name == "uc" and value is not None:
                state.unicode_skip = value
            elif name == "u" and value is not None:
                # RTF writes characters past 32767 as negative numbers.
                code_point = value
                if value < 0:
                    code_point = value + _UNICODE_SIGNED_BASE
                add(chr(code_point))
                pending_skip = state.unicode_skip
        elif text is not None:
            if state.is_colour_table:
                # Each ";" ends a colour: the parts given since the one before, or none at all.
                for _end in range(text.count(_COLOUR_END.encode())):
                    if has_colour_part:
                        colours.append(tuple(colour))
                    else:
                        colours.append(None)
                    colour = [0] * len(_COLOUR_PARTS)
                    has_colour_part = False
            add(text.decode(code_page, errors="replace"))
    if runs:
        end_paragraph()
    return [block for block in blocks if any(run.text.strip() != "" for run in block.runs)]


# --- Word 97-2003 (.doc) ------------------------------------------------------------------
# [MS-DOC]: the WordDocument stream starts with the FIB, which says which table stream holds
# the CLX; the CLX's piece table maps the main text's characters to where they are stored, as
# Windows-1252 (one byte each) or UTF-16. Text only: no formatting, pictures or tables' shape.

_WORD_STREAM = "WordDocument"
_TABLE_STREAMS = ("0Table", "1Table")
_WORD_SIGNATURE = 0xA5EC
# Word 97's FIB and later; Word 6 and 95 kept their text otherwise.
_FIRST_WORD97_FIB = 193
_FIB_IDENT_OFFSET = 0
_FIB_VERSION_OFFSET = 2
_FIB_FLAGS_OFFSET = 0x0A
_FIB_ENCRYPTED = 0x0100
_FIB_TABLE_1 = 0x0200
_FIB_BASE_BYTES = 32
_U16_BYTES = 2
_U32_BYTES = 4
# Where the stories' lengths are in the FIB's 32-bit array: the main text (ccpText), then the
# footnotes, headers and footers, comments, endnotes, text boxes and headers' text boxes, kept
# in that order after it. All are the document's words: reading the main text alone left out a
# letterhead's address and a title set in the header (the maintainer's .doc files, 2026-11-03).
_STORY_LENGTH_INDEXES = (3, 4, 5, 7, 8, 9, 10)
_CLX_PAIR_INDEX = 33
_FC_LCB_PAIR_BYTES = 8
_CLX_PRC = 0x01
_CLX_PCDT = 0x02
# A Prc's tag and size, a Pcdt's tag and size.
_PRC_HEADER_BYTES = 3
_PCDT_HEADER_BYTES = 5
_PCD_BYTES = 8
_PCD_FC_OFFSET = 2
_PIECE_COMPRESSED = 0x40000000
_PIECE_FC_MASK = 0x3FFFFFFF
_COMPRESSED_FC_DIVISOR = 2
_COMPRESSED_CODE_PAGE = "cp1252"
_WIDE_CODE = "utf-16-le"
_WIDE_CHARACTER_BYTES = 2
_DECODE_ERRORS = {_COMPRESSED_CODE_PAGE: "replace", _WIDE_CODE: "surrogatepass"}
# Characters with a meaning in Word's text.
_FIELD_BEGIN = "\x13"
_FIELD_SEPARATOR = "\x14"
_FIELD_END = "\x15"
_DOC_PARAGRAPH_ENDS = frozenset({"\r", "\x07", "\x0c"})
_DOC_LINE_BREAK = "\x0b"
_DOC_TAB = "\t"
_DOC_REPLACED = {"\x1e": "\u2011", "\x1f": ""}
_FIRST_PRINTABLE = 0x20
# How the characters are set: the FIB's PlcBteChpx (pair 12) lists 512-byte pages (FKPs) in the
# WordDocument stream; each page lists runs of file positions and each run's character
# properties (sprms). Read are bold, italic, strikethrough, underline and highlight; formatting
# that can't be read leaves its text plain.
_CHPX_PAIR_INDEX = 12
_FKP_PAGE_BYTES = 512
_FKP_RUN_COUNT_OFFSET = _FKP_PAGE_BYTES - 1
_PAGE_NUMBER_MASK = 0x3FFFFF
_CHPX_OFFSET_UNIT = 2
_SPRA_SHIFT = 13
_SPRM_BYTES = 2
# The operand's size by the sprm's spra; 6 is variable, its first byte the size.
_OPERAND_BYTES = {0: 1, 1: 1, 2: 2, 3: 4, 4: 2, 5: 2, 7: 3}
_VARIABLE_SPRA = 6
_SPRM_BOLD = 0x0835
_SPRM_ITALIC = 0x0836
_SPRM_STRIKE = 0x0837
_SPRM_DOUBLE_STRIKE = 0x2A53
_SPRM_UNDERLINE = 0x2A3E
_SPRM_HIGHLIGHT = 0x2A0C
# A toggle's on: 1, or 0x81 (the opposite of the style's, which is read as off).
_TOGGLES_ON = frozenset({1, 0x81})


def _u16(data: bytes, offset: int) -> int:
    if offset < 0 or offset + _U16_BYTES > len(data):
        raise UnreadableDocument("a Word document cut short")
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + _U32_BYTES > len(data):
        raise UnreadableDocument("a Word document cut short")
    return struct.unpack_from("<I", data, offset)[0]


def _doc_streams(content: bytes) -> Tuple[bytes, Dict[str, bytes]]:
    """The WordDocument stream and the table streams there are, read from the OLE file."""
    if not olefile.isOleFile(BytesIO(content)):
        raise UnreadableDocument("not a Word document")
    # The user's file: olefile says OleFileError (an OSError), or now and then ValueError, for a
    # damaged one (2,000 damaged copies of a test document, 2026-11-03).
    capture = CapturedExceptionContext(OSError, ValueError, boundary='app/services/document_text.py:_doc_streams:ole_capture')
    streams: Tuple[bytes, Dict[str, bytes]] = (b"", {})
    with capture:
        streams = _read_doc_streams(content)
    if capture.captured_exception is not None:
        raise UnreadableDocument("a damaged Word document") from capture.captured_exception
    return streams


def _read_doc_streams(content: bytes) -> Tuple[bytes, Dict[str, bytes]]:
    with olefile.OleFileIO(BytesIO(content)) as ole:
        if not ole.exists(_WORD_STREAM):
            raise UnreadableDocument("an OLE file holding no Word document")
        word = ole.openstream(_WORD_STREAM).read()
        tables = {name: ole.openstream(name).read() for name in _TABLE_STREAMS if ole.exists(name)}
    return word, tables


def _doc_text(content: bytes) -> Tuple[str, List[_Look]]:
    """A Word 97-2003 document's text, its characters as Word stores them: the main text, then
    its other stories (_STORY_LENGTH_INDEXES); and each character's look."""
    word, tables = _doc_streams(content)
    if _u16(word, _FIB_IDENT_OFFSET) != _WORD_SIGNATURE:
        raise UnreadableDocument("not a Word document")
    if _u16(word, _FIB_VERSION_OFFSET) < _FIRST_WORD97_FIB:
        raise UnreadableDocument("a Word document older than Word 97")
    flags = _u16(word, _FIB_FLAGS_OFFSET)
    if flags & _FIB_ENCRYPTED:
        raise UnreadableDocument("a Word document behind a password")
    # The FIB says which of the two table streams is this document's.
    table_name = _TABLE_STREAMS[0]
    if flags & _FIB_TABLE_1:
        table_name = _TABLE_STREAMS[1]
    if table_name not in tables:
        raise UnreadableDocument("a Word document missing its table")
    # FibBase, then csw 16-bit words, then cslw 32-bit longs, then cbRgFcLcb (fc, lcb) pairs.
    offset = _FIB_BASE_BYTES
    offset += _U16_BYTES + _u16(word, offset) * _U16_BYTES
    long_count = _u16(word, offset)
    longs = offset + _U16_BYTES
    if long_count <= max(_STORY_LENGTH_INDEXES):
        raise UnreadableDocument("a Word document without its text's length")
    text_length = sum(_u32(word, longs + index * _U32_BYTES) for index in _STORY_LENGTH_INDEXES)
    offset = longs + long_count * _U32_BYTES
    pair_count = _u16(word, offset)
    if pair_count <= _CLX_PAIR_INDEX:
        raise UnreadableDocument("a Word document without its table of pieces")
    pair = offset + _U16_BYTES + _CLX_PAIR_INDEX * _FC_LCB_PAIR_BYTES
    clx_at, clx_length = _u32(word, pair), _u32(word, pair + _U32_BYTES)
    table = tables[table_name]
    if clx_at + clx_length > len(table):
        raise UnreadableDocument("a Word document whose table of pieces is cut short")
    text, positions = _pieces_text(word, table[clx_at:clx_at + clx_length], text_length)
    looks_pair = offset + _U16_BYTES + _CHPX_PAIR_INDEX * _FC_LCB_PAIR_BYTES
    looks = _character_looks(word, table, _u32(word, looks_pair), _u32(word, looks_pair + _U32_BYTES))
    starts = [start for start, _end, _look in looks]
    return text, [_look_at(looks, starts, position) for position in positions]


def _pieces_text(word: bytes, clx: bytes, text_length: int) -> Tuple[str, List[int]]:
    """The text's first text_length characters, from the CLX's pieces, with where each is in
    the WordDocument stream."""
    position = 0
    while position < len(clx) and clx[position] == _CLX_PRC:
        position += _PRC_HEADER_BYTES + _u16(clx, position + 1)
    if position >= len(clx) or clx[position] != _CLX_PCDT:
        raise UnreadableDocument("a Word document without its pieces")
    plc_length = _u32(clx, position + 1)
    plc = clx[position + _PCDT_HEADER_BYTES:position + _PCDT_HEADER_BYTES + plc_length]
    piece_count = (len(plc) - _U32_BYTES) // (_U32_BYTES + _PCD_BYTES)
    if piece_count <= 0 or len(plc) != _U32_BYTES + piece_count * (_U32_BYTES + _PCD_BYTES):
        raise UnreadableDocument("a Word document whose pieces don't add up")
    descriptors = (piece_count + 1) * _U32_BYTES
    parts: List[str] = []
    positions: List[int] = []
    for index in range(piece_count):
        start, end = _u32(plc, index * _U32_BYTES), _u32(plc, (index + 1) * _U32_BYTES)
        end = min(end, text_length)
        if start >= end:
            continue
        stored = _u32(plc, descriptors + index * _PCD_BYTES + _PCD_FC_OFFSET)
        count = end - start
        # Windows-1252, a byte a character, stored at half the offset given; else UTF-16.
        at = stored & _PIECE_FC_MASK
        size = count * _WIDE_CHARACTER_BYTES
        code = _WIDE_CODE
        if stored & _PIECE_COMPRESSED:
            at //= _COMPRESSED_FC_DIVISOR
            size = count
            code = _COMPRESSED_CODE_PAGE
        raw = word[at:at + size]
        if len(raw) != size:
            raise UnreadableDocument("a Word document whose text is cut short")
        # UTF-16 a unit at a time (a character past U+FFFF is two, rejoined in _doc_blocks), so
        # each character keeps its own file position.
        decoded = raw.decode(code, errors=_DECODE_ERRORS[code])
        if len(decoded) != count:
            raise UnreadableDocument("a Word document whose text doesn't decode one character for each")
        parts.append(decoded)
        step = size // count
        positions.extend(at + index * step for index in range(count))
    return "".join(parts), positions


def _character_looks(word: bytes, table: bytes, at: int, length: int) -> List[Tuple[int, int, _Look]]:
    """The runs of file positions the FKPs set, each with its look, in order; none when the
    table of pages can't be read (the text stays, plain)."""
    plc = table[at:at + length]
    page_count = (len(plc) - _U32_BYTES) // (_U32_BYTES + _U32_BYTES)
    if length == 0 or len(plc) != length or page_count <= 0:
        return []
    looks: List[Tuple[int, int, _Look]] = []
    for index in range(page_count):
        page_number = _u32(plc, (page_count + 1) * _U32_BYTES + index * _U32_BYTES) & _PAGE_NUMBER_MASK
        page = word[page_number * _FKP_PAGE_BYTES:(page_number + 1) * _FKP_PAGE_BYTES]
        if len(page) != _FKP_PAGE_BYTES:
            continue
        run_count = page[_FKP_RUN_COUNT_OFFSET]
        if (run_count + 1) * _U32_BYTES + run_count > _FKP_RUN_COUNT_OFFSET:
            continue
        for run in range(run_count):
            start, end = _u32(page, run * _U32_BYTES), _u32(page, (run + 1) * _U32_BYTES)
            properties_at = page[(run_count + 1) * _U32_BYTES + run] * _CHPX_OFFSET_UNIT
            look = _PLAIN
            if properties_at != 0:
                look = _chpx_look(page, properties_at)
            looks.append((start, end, look))
    looks.sort(key=lambda found: found[0])
    return looks


def _chpx_look(page: bytes, at: int) -> _Look:
    """A run's look from its sprms; a sprm cut short ends the reading of them."""
    properties = page[at + 1:at + 1 + page[at]]
    is_bold = is_italic = is_underline = is_strike = False
    highlight = NO_HIGHLIGHT
    position = 0
    while position + _SPRM_BYTES <= len(properties):
        sprm = struct.unpack_from("<H", properties, position)[0]
        position += _SPRM_BYTES
        spra = sprm >> _SPRA_SHIFT
        if spra == _VARIABLE_SPRA:
            if position >= len(properties):
                break
            size = 1 + properties[position]
        else:
            size = _OPERAND_BYTES[spra]
        operand = properties[position:position + size]
        position += size
        if len(operand) != size:
            break
        if sprm == _SPRM_BOLD:
            is_bold = operand[0] in _TOGGLES_ON
        elif sprm == _SPRM_ITALIC:
            is_italic = operand[0] in _TOGGLES_ON
        elif sprm in (_SPRM_STRIKE, _SPRM_DOUBLE_STRIKE):
            is_strike = operand[0] in _TOGGLES_ON
        elif sprm == _SPRM_UNDERLINE:
            is_underline = operand[0] != 0
        elif sprm == _SPRM_HIGHLIGHT:
            highlight = highlight_of_number(operand[0])
    return _Look(is_bold=is_bold, is_italic=is_italic, is_underline=is_underline, is_strike=is_strike, highlight=highlight)


def _look_at(looks: List[Tuple[int, int, _Look]], starts: List[int], position: int) -> _Look:
    """The look of the character at a file position: the run holding it (starts: the runs'
    first positions), else plain."""
    index = bisect.bisect_right(starts, position) - 1
    if index < 0 or position >= looks[index][1]:
        return _PLAIN
    return looks[index][2]


def _doc_blocks(content: bytes) -> List[_Block]:
    """A .doc's paragraphs (a table's cells each one): a field shows its result, not its code;
    pictures' and objects' marks are dropped."""
    blocks: List[_Block] = []
    runs: List[_Run] = []
    text: List[str] = []
    look = _PLAIN
    # Each open field: whether its code (before the separator) is being read.
    fields: List[bool] = []

    def flush_text() -> None:
        if text:
            # Halves of a character (UTF-16 surrogates) joined again; a lone one is U+FFFD.
            whole = "".join(text).encode(_WIDE_CODE, "surrogatepass").decode(_WIDE_CODE, "replace")
            runs.append(_Run(text=whole, look=look, is_break=False))
            text.clear()

    characters, looks = _doc_text(content)
    for character, character_look in zip(characters, looks):
        if character_look != look:
            flush_text()
            look = character_look
        if character == _FIELD_BEGIN:
            fields.append(True)
        elif character == _FIELD_SEPARATOR:
            if fields:
                fields[-1] = False
        elif character == _FIELD_END:
            if fields:
                fields.pop()
        elif any(fields):
            continue
        elif character in _DOC_PARAGRAPH_ENDS:
            flush_text()
            blocks.append(_Block(tag="p", runs=tuple(runs), rows=()))
            runs.clear()
        elif character == _DOC_LINE_BREAK:
            flush_text()
            runs.append(_Run(text="", look=_PLAIN, is_break=True))
        elif character in _DOC_REPLACED:
            text.append(_DOC_REPLACED[character])
        elif ord(character) >= _FIRST_PRINTABLE or character == _DOC_TAB:
            text.append(character)
    flush_text()
    if runs:
        blocks.append(_Block(tag="p", runs=tuple(runs), rows=()))
    return [block for block in blocks if any(run.text.strip() != "" for run in block.runs)]


# --- As note HTML -----------------------------------------------------------------------


def _runs_html(runs: Tuple[_Run, ...]) -> str:
    """The runs as HTML, neighbours of the same look as one (<b>a</b><b>b</b> is <b>ab</b>)."""
    parts: List[str] = []
    index = 0
    while index < len(runs):
        if runs[index].is_break:
            parts.append("<br>")
            index += 1
            continue
        look = runs[index].look
        texts: List[str] = []
        while index < len(runs) and not runs[index].is_break and runs[index].look == look:
            texts.append(runs[index].text)
            index += 1
        parts.append(_looked_html(html.escape("".join(texts), quote=False), look))
    return "".join(parts)


def _looked_html(piece: str, look: _Look) -> str:
    """A piece of text set as its look: a highlight is the viewer's mark (document_highlights.py)."""
    if piece.strip() == "":
        return piece
    if look.is_italic:
        piece = f"<i>{piece}</i>"
    if look.is_bold:
        piece = f"<b>{piece}</b>"
    if look.is_underline:
        piece = f"<u>{piece}</u>"
    if look.is_strike:
        piece = f"<s>{piece}</s>"
    if look.highlight != NO_HIGHLIGHT:
        piece = f'<mark class="{HIGHLIGHT_CLASS_PREFIX}{look.highlight}">{piece}</mark>'
    return piece


def _blocks_html(blocks: List[_Block]) -> str:
    out = ""
    in_list = False
    for block in blocks:
        if block.tag == "li" and not in_list:
            out += "<ul>"
            in_list = True
        if block.tag != "li" and in_list:
            out += "</ul>"
            in_list = False
        if block.tag == "table":
            rows = "".join("<tr>" + "".join(f"<td>{html.escape(cell, quote=False)}</td>" for cell in row) + "</tr>" for row in block.rows)
            out += f"<table>{rows}</table>"
            continue
        inner = _runs_html(block.runs)
        if inner == "" and block.tag == "p":
            continue
        out += f"<{block.tag}>{inner}</{block.tag}>"
    if in_list:
        out += "</ul>"
    return out
