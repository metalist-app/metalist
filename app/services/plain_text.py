"""The text of a plain text file (text, Markdown, code, CSV, JSON) and of a web page, kept for
search as a PDF's is (docs/ready-to-build/files-shown-not-copied.md §2). Python alone."""

from __future__ import annotations

from html.parser import HTMLParser
from typing import List

_UTF8_BOM = b"\xef\xbb\xbf"
# Text that isn't UTF-8 keeps what can be read of it: a word with an odd letter still reads.
_REPLACE = "replace"
# A web page's parts that aren't its text.
_SKIPPED_ELEMENTS = frozenset({"head", "script", "style", "template", "noscript", "svg"})


def file_text(content: bytes) -> str:
    """A text file's text: UTF-8, its byte order mark left out."""
    if content.startswith(_UTF8_BOM):
        content = content[len(_UTF8_BOM):]
    return content.decode("utf-8", errors=_REPLACE)


def web_page_text(content: bytes) -> str:
    """A web page's visible text: its head, scripts and styles left out."""
    reader = _PageText()
    reader.feed(file_text(content))
    reader.close()
    return " ".join(reader.pieces)


class _PageText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pieces: List[str] = []
        self._skipped_depth = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _SKIPPED_ELEMENTS:
            self._skipped_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_ELEMENTS and self._skipped_depth > 0:
            self._skipped_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skipped_depth == 0:
            self.pieces.append(data)
