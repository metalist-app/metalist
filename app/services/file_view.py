"""A file as the viewer shows it (docs/ready-to-build/files-shown-not-copied.md §4): made when
opened, never stored; no file is copied into a note.

A PDF is shown by the browser's own viewer (VIEW_PDF). The rest (VIEW_PAGE) become note HTML:
text as it is, Markdown, CSV, JSON and code with the meta tag that draws them as a note
(`@markdown`, `@csv`, `@json`, `@code=<language>`), a Word document through mammoth, an RTF
through MetaList's own reader, a web page's body, each sanitized as a note's content.
"""

from __future__ import annotations

import html
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from xml.parsers.expat import ExpatError

import mammoth

from app.security.note_html import sanitize_note_html, sanitize_viewed_document_html
from app.services.document_text import (
    DOC_EXTENSION, DOCUMENT_EXTENSIONS, DOCX_EXTENSION, RTF_EXTENSION, UnreadableDocument, document_html, require_safe_docx,
)
from app.services.document_highlights import DOCX_HIGHLIGHT_NAMES, HIGHLIGHT_CLASS_PREFIX
from app.services.email_files import ReadEmail, read_email
from app.services.exception_capture import CapturedExceptionContext
from app.services.plain_text import file_text
from app.utils.byte_sizes import MIB
from app.utils.text_utils import strip_html


# A text file shows its first 5 MB; the viewer says the rest is in the download (the maintainer,
# 2026-11-03).
MAX_VIEW_TEXT_BYTES = 5 * MIB
# Drawn HTML larger than this isn't shown (a Word document's pictures go first).
MAX_VIEW_HTML_BYTES = 32 * MIB
_UTF8 = "utf-8"
# A web page, a Word document or an RTF larger than this is not read for the viewer (its text
# still is, for search).
_MAX_PAGE_SOURCE_BYTES = 20 * MIB
# A Word document's pictures, left out when keeping them would pass MAX_VIEW_HTML_BYTES.
_IMAGE_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_HTML_BODY_RE = re.compile(r"<body\b[^>]*>(.*?)(?:</body\s*>|\Z)", re.IGNORECASE | re.DOTALL)
# How the viewer shows a file: the browser's PDF viewer, as note HTML, or not at all (a card
# with Download only).
VIEW_PDF = "pdf"
VIEW_PAGE = "page"
# An email, or a web page saved whole: its headers and attachments beside its body (2026-11-03).
VIEW_EMAIL = "email"
NO_VIEW = ""
_PDF_ENDING = ".pdf"
# The kinds of file shown as note HTML, by ending.
PREVIEW_TEXT = "text"
PREVIEW_DATA = "data"
PREVIEW_CODE = "code"
PREVIEW_HTML = "html"
# A Word document (through mammoth: headings, bold, italics, lists, tables, links, footnotes,
# pictures) or an RTF (MetaList's own reader, document_text.py: paragraphs, bold, italics).
PREVIEW_DOCUMENT = "document"
NO_PREVIEW = ""

STATUS_READY = "ready"
STATUS_NOT_PREVIEWABLE = "not_previewable"
STATUS_TOO_LARGE = "too_large"
# A web page or a document with nothing left to show once sanitized.
STATUS_NO_TEXT = "no_text"
# A Word document or an RTF that can't be read (damaged).
STATUS_NOT_READABLE = "not_readable"


@dataclass(frozen=True)
class _TextFileKind:
    badge: str
    render_tag: str


_TEXT_FILE_KINDS_BY_EXTENSION = {
    ".txt": _TextFileKind(badge=".TXT", render_tag=""),
    ".md": _TextFileKind(badge=".MD", render_tag="@markdown"),
    ".markdown": _TextFileKind(badge=".MD", render_tag="@markdown"),
    ".csv": _TextFileKind(badge=".CSV", render_tag="@csv"),
    ".json": _TextFileKind(badge=".JSON", render_tag="@json"),
}
_DATA_EXTENSIONS = frozenset({".csv", ".json"})
# Code files by ending, with the language @code= draws them in (Pygments names).
_CODE_LANGUAGES_BY_EXTENSION = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript", ".ts": "typescript", ".tsx": "tsx", ".jsx": "jsx",
    ".sh": "bash", ".zsh": "zsh", ".rb": "ruby", ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin",
    ".swift": "swift", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cs": "csharp", ".php": "php",
    ".sql": "sql", ".css": "css", ".scss": "scss", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".xml": "xml",
}
_HTML_EXTENSIONS = frozenset({".html", ".htm"})
# Files whose text is read as it is for search (file_text_search.py), and web pages, whose
# visible text is.
PLAIN_TEXT_ENDINGS = frozenset(_TEXT_FILE_KINDS_BY_EXTENSION) | frozenset(_CODE_LANGUAGES_BY_EXTENSION)
WEB_PAGE_ENDINGS = _HTML_EXTENSIONS


@dataclass(frozen=True)
class FileView:
    """A file as note HTML for the viewer, or why it can't be.

    `status` is "ready", "not_previewable" (not shown as note HTML), "too_large", "not_readable"
    (damaged) or "no_text" (nothing to show). Content and tag are empty unless it is "ready";
    `is_cut` says a text file shows only its first MAX_VIEW_TEXT_BYTES.
    """

    status: str
    content_html: str
    render_tag: str
    is_cut: bool


def text_file_badge(original_filename: str) -> str:
    """The pill label for a previewable text file by its extension, or "" for any other file."""
    assert isinstance(original_filename, str) and original_filename != ""
    extension = PurePath(original_filename).suffix.lower()
    if extension not in _TEXT_FILE_KINDS_BY_EXTENSION:
        return ""
    return _TEXT_FILE_KINDS_BY_EXTENSION[extension].badge


def preview_kind_of(original_filename: str) -> str:
    """The kind of preview a file gets by its ending, or NO_PREVIEW."""
    assert isinstance(original_filename, str) and original_filename != ""
    extension = PurePath(original_filename).suffix.lower()
    if extension in DOCUMENT_EXTENSIONS:
        return PREVIEW_DOCUMENT
    if extension in _DATA_EXTENSIONS:
        return PREVIEW_DATA
    if extension in _TEXT_FILE_KINDS_BY_EXTENSION:
        return PREVIEW_TEXT
    if extension in _CODE_LANGUAGES_BY_EXTENSION:
        return PREVIEW_CODE
    if extension in _HTML_EXTENSIONS:
        return PREVIEW_HTML
    return NO_PREVIEW


def view_kind_of(original_filename: str) -> str:
    """How the viewer shows a file by its ending: VIEW_PDF, VIEW_PAGE or NO_VIEW."""
    assert isinstance(original_filename, str) and original_filename != ""
    if PurePath(original_filename).suffix.lower() == _PDF_ENDING:
        return VIEW_PDF
    if preview_kind_of(original_filename) == NO_PREVIEW:
        return NO_VIEW
    return VIEW_PAGE


def build_file_view(*, original_filename: str, content_bytes: bytes) -> FileView:
    """A VIEW_PAGE file as note HTML (module docstring)."""
    assert isinstance(original_filename, str) and original_filename != ""
    assert isinstance(content_bytes, bytes)
    kind = preview_kind_of(original_filename)
    extension = PurePath(original_filename).suffix.lower()
    if kind == PREVIEW_HTML:
        return _html_view(content_bytes)
    if kind == PREVIEW_DOCUMENT:
        return _document_view(original_filename, content_bytes)
    if kind == NO_PREVIEW:
        return _no_view(STATUS_NOT_PREVIEWABLE)
    text = file_text(content_bytes)
    is_cut = len(text.encode(_UTF8)) > MAX_VIEW_TEXT_BYTES
    if is_cut:
        text = text.encode(_UTF8)[:MAX_VIEW_TEXT_BYTES].decode(_UTF8, errors="ignore")
    if kind == PREVIEW_CODE:
        render_tag = f"@code={_CODE_LANGUAGES_BY_EXTENSION[extension]}"
    else:
        render_tag = _TEXT_FILE_KINDS_BY_EXTENSION[extension].render_tag
    return FileView(status=STATUS_READY, content_html=plain_text_to_note_html(text), render_tag=render_tag, is_cut=is_cut)


def _no_view(status: str) -> FileView:
    return FileView(status=status, content_html="", render_tag="", is_cut=False)


def _html_view(content_bytes: bytes) -> FileView:
    """A web page as a note shows pasted HTML: its body, sanitized as a note's content
    (scripts, styles and the page's head left out)."""
    if len(content_bytes) > _MAX_PAGE_SOURCE_BYTES:
        return _no_view(STATUS_TOO_LARGE)
    text = file_text(content_bytes)
    body = _HTML_BODY_RE.search(text)
    if body is not None:
        text = body.group(1)
    content_html = sanitize_note_html(text).strip()
    if strip_html(content_html).strip() == "":
        return _no_view(STATUS_NO_TEXT)
    if len(content_html.encode(_UTF8)) > MAX_VIEW_HTML_BYTES:
        return _no_view(STATUS_TOO_LARGE)
    return FileView(status=STATUS_READY, content_html=content_html, render_tag="", is_cut=False)


def _document_view(original_filename: str, content_bytes: bytes) -> FileView:
    """A Word document (mammoth), an RTF or a .doc (document_text.py) as note HTML, sanitized as a note's
    content. A Word document whose pictures would pass MAX_VIEW_HTML_BYTES shows without them."""
    if len(content_bytes) > _MAX_PAGE_SOURCE_BYTES:
        return _no_view(STATUS_TOO_LARGE)
    capture = CapturedExceptionContext(UnreadableDocument, boundary='app/services/file_view.py:_document_view:document_capture')
    converted = ""
    with capture:
        if PurePath(original_filename).suffix.lower() == DOCX_EXTENSION:
            converted = _word_html(content_bytes)
        else:
            # An RTF, or a Word 97-2003 .doc (its text, paragraph by paragraph), read here.
            assert PurePath(original_filename).suffix.lower() in (RTF_EXTENSION, DOC_EXTENSION)
            converted = document_html(original_filename, content_bytes)
    if capture.captured_exception is not None:
        return _no_view(STATUS_NOT_READABLE)
    # Sanitized as a note's content, its highlights kept (the viewer's own pass).
    content_html = sanitize_viewed_document_html(converted).strip()
    if len(content_html.encode(_UTF8)) > MAX_VIEW_HTML_BYTES:
        content_html = sanitize_viewed_document_html(_IMAGE_TAG_RE.sub("", converted)).strip()
    if strip_html(content_html).strip() == "" and _IMAGE_TAG_RE.search(content_html) is None:
        return _no_view(STATUS_NO_TEXT)
    if len(content_html.encode(_UTF8)) > MAX_VIEW_HTML_BYTES:
        return _no_view(STATUS_TOO_LARGE)
    return FileView(status=STATUS_READY, content_html=content_html, render_tag="", is_cut=False)


# What mammoth shows beyond its own defaults: a run's highlight as the viewer's mark (one of
# Word's 16, document_highlights.py) and its underline, which it leaves out unless told.
_WORD_STYLE_MAP = "\n".join([
    *(f"highlight[color='{word_name}'] => mark.{HIGHLIGHT_CLASS_PREFIX}{name}" for word_name, name in DOCX_HIGHLIGHT_NAMES.items()),
    "u => u",
])


def _word_html(content_bytes: bytes) -> str:
    """A Word document as HTML by mammoth (from its structure: headings, bold, italics, lists,
    tables, links, footnotes, pictures inline). Raises UnreadableDocument for one that can't be
    read or isn't safe to hand over (document_text.require_safe_docx)."""
    require_safe_docx(content_bytes)
    capture = CapturedExceptionContext(
        zipfile.BadZipFile, OSError, ExpatError, boundary='app/services/file_view.py:_word_html:mammoth_capture',
    )
    converted = ""
    with capture:
        converted = mammoth.convert_to_html(BytesIO(content_bytes), style_map=_WORD_STYLE_MAP).value
    if capture.captured_exception is not None:
        raise UnreadableDocument("a damaged Word document") from capture.captured_exception
    return converted


def build_email_view(content_bytes: bytes) -> tuple[FileView, ReadEmail]:
    """An email as the viewer shows it: its body (the HTML version, sanitized as read, else the
    plain text) as note HTML, and the email for its headers and attachments."""
    assert isinstance(content_bytes, bytes)
    email = read_email(content_bytes)
    body = email.body_html
    if body == "":
        body = plain_text_to_note_html(email.body_text)
    if strip_html(body).strip() == "" and _IMAGE_TAG_RE.search(body) is None:
        return FileView(status=STATUS_NO_TEXT, content_html="", render_tag="", is_cut=False), email
    return FileView(status=STATUS_READY, content_html=body, render_tag="", is_cut=False), email


def plain_text_to_note_html(text: str) -> str:
    """Note HTML holding `text` line for line, as the renderers read it back."""
    assert isinstance(text, str)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n").split("\n")
    return "<br>".join(html.escape(line, quote=False) for line in lines)
