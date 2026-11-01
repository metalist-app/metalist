"""Files dropped or imported into MetaList: their pill label and their preview note.

A dropped `.txt`, `.md`, `.csv` or `.json` file, a code file or a web page is stored
like any file, and its text is also copied into a child note of the note holding the file's
pill, so it can be read, searched and collapsed like any note: note data on top of the file
data (docs/ready-to-build/folder-import-and-file-previews.md §5). Markdown, CSV, JSON and code
children get the meta tag that renders them (`@markdown`, `@csv`, `@json`, `@code=<language>`);
a web page's is its HTML, sanitized as a note's. The child is an ordinary note: editing it
never changes the stored file (docs/ui/references.md).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import List, Tuple

from app.security.note_html import sanitize_note_html
from app.utils.sampling import scaled_total, spread_sample
from app.utils.text_utils import strip_html


# Larger files keep only their pill: a preview that long is not a preview.
MAX_PREVIEW_BYTES = 200 * 1024
_UTF8_BOM = b"\xef\xbb\xbf"
_UTF8 = "utf-8"
# A web page larger than this is not read at all (its scripts and styles go, but reading
# them costs); what is left must still fit MAX_PREVIEW_BYTES.
_MAX_HTML_SOURCE_BYTES = 5 * 1024 * 1024
_HTML_BODY_RE = re.compile(r"<body\b[^>]*>(.*?)(?:</body\s*>|\Z)", re.IGNORECASE | re.DOTALL)
# How many files of a kind an import's estimate previews: spread from the smallest to the
# largest.
ESTIMATE_SAMPLE_COUNT = 4

# The kinds of preview, by a file's ending: the import's Previews screen ticks them by kind.
PREVIEW_TEXT = "text"
PREVIEW_DATA = "data"
PREVIEW_CODE = "code"
PREVIEW_HTML = "html"
# The kinds an import of a folder of files asks about (its text files are notes already). A PDF
# gets no preview note: its text is to be searchable with the file instead
# (folder-import-and-file-previews.md, "Searchable file text").
IMPORT_PREVIEW_KINDS = (PREVIEW_CODE, PREVIEW_HTML, PREVIEW_DATA)
NO_PREVIEW = ""

STATUS_READY = "ready"
STATUS_NOT_PREVIEWABLE = "not_previewable"
STATUS_TOO_LARGE = "too_large"
STATUS_NOT_TEXT = "not_text"
# A web page with nothing left to show once sanitized.
STATUS_NO_TEXT = "no_text"


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


@dataclass(frozen=True)
class FileTextPreview:
    """What a dropped file's preview child gets, or why it gets none.

    `status` is "ready", "not_previewable" (no preview for its kind), "too_large", "not_text"
    (not UTF-8) or "no_text" (a web page with nothing to show). Content and tags are empty
    unless it is "ready".
    """

    status: str
    content_html: str
    render_tag: str


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
    if extension in _DATA_EXTENSIONS:
        return PREVIEW_DATA
    if extension in _TEXT_FILE_KINDS_BY_EXTENSION:
        return PREVIEW_TEXT
    if extension in _CODE_LANGUAGES_BY_EXTENSION:
        return PREVIEW_CODE
    if extension in _HTML_EXTENSIONS:
        return PREVIEW_HTML
    return NO_PREVIEW


def build_file_text_preview(*, original_filename: str, content_bytes: bytes) -> FileTextPreview:
    assert isinstance(original_filename, str) and original_filename != ""
    assert isinstance(content_bytes, bytes)
    kind = preview_kind_of(original_filename)
    extension = PurePath(original_filename).suffix.lower()
    if kind == PREVIEW_HTML:
        return _html_preview(content_bytes)
    if kind == NO_PREVIEW:
        return _no_preview(STATUS_NOT_PREVIEWABLE)
    if len(content_bytes) > MAX_PREVIEW_BYTES:
        return _no_preview(STATUS_TOO_LARGE)
    text = _utf8_text(content_bytes)
    if text is None:
        # A user's file in another encoding: it keeps its pill without a preview.
        return _no_preview(STATUS_NOT_TEXT)
    if kind == PREVIEW_CODE:
        render_tag = f"@code={_CODE_LANGUAGES_BY_EXTENSION[extension]}"
    else:
        render_tag = _TEXT_FILE_KINDS_BY_EXTENSION[extension].render_tag
    return FileTextPreview(status=STATUS_READY, content_html=plain_text_to_note_html(text), render_tag=render_tag)


def estimated_note_bytes(files: List[Tuple[Path, int]]) -> int:
    """About how many bytes of note data the previews of files ((path, size) pairs, one kind)
    add: a few of them previewed, from the smallest to the largest, the rest taken alike."""
    if not files:
        return 0
    by_size = sorted(files, key=lambda pair: pair[1])
    measured = [(size, _preview_bytes(path)) for path, size in spread_sample(by_size, ESTIMATE_SAMPLE_COUNT)]
    return scaled_total(measured, sum(size for _path, size in by_size))


def _preview_bytes(path: Path) -> int:
    preview = build_file_text_preview(original_filename=path.name, content_bytes=path.read_bytes())
    return len(preview.content_html.encode(_UTF8))


def _no_preview(status: str) -> FileTextPreview:
    return FileTextPreview(status=status, content_html="", render_tag="")


def _utf8_text(content_bytes: bytes) -> str | None:
    text_bytes = content_bytes.removeprefix(_UTF8_BOM)
    text = text_bytes.decode(_UTF8, errors="replace")
    if text.encode(_UTF8) != text_bytes:
        return None
    return text


def _html_preview(content_bytes: bytes) -> FileTextPreview:
    """A web page as a note shows pasted HTML: its body, sanitized as a note's content
    (scripts, styles and the page's head left out)."""
    if len(content_bytes) > _MAX_HTML_SOURCE_BYTES:
        return _no_preview(STATUS_TOO_LARGE)
    text = _utf8_text(content_bytes)
    if text is None:
        return _no_preview(STATUS_NOT_TEXT)
    body = _HTML_BODY_RE.search(text)
    if body is not None:
        text = body.group(1)
    content_html = sanitize_note_html(text).strip()
    if strip_html(content_html).strip() == "":
        return _no_preview(STATUS_NO_TEXT)
    if len(content_html.encode(_UTF8)) > MAX_PREVIEW_BYTES:
        return _no_preview(STATUS_TOO_LARGE)
    return FileTextPreview(status=STATUS_READY, content_html=content_html, render_tag="")


def plain_text_to_note_html(text: str) -> str:
    """Note HTML holding `text` line for line, as the renderers read it back."""
    assert isinstance(text, str)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n").split("\n")
    return "<br>".join(html.escape(line, quote=False) for line in lines)
