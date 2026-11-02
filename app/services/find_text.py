"""Find in the list (docs/ui/find.md): how a note's rendered HTML reads, and where a
find's text occurs in it.

The reading and the matching are those of the browser's marks
(app/static/js/modules/mode-manager/services/search-highlight-service.js readVisibleText,
search-highlight-matching.js findPhraseMatches), so a note's count here is the number of
marks the browser paints in it.
"""

from __future__ import annotations

from html.parser import HTMLParser
import re

# Elements whose start and end break the text the way the search reads it: one space
# (search-highlight-service.js TEXT_BREAKING_ELEMENTS).
_TEXT_BREAKING_ELEMENTS = frozenset({
    "address", "article", "aside", "blockquote", "br", "dd", "details", "div", "dl", "dt",
    "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr",
    "li", "main", "ol", "p", "pre", "section", "summary", "table", "tbody", "td", "tfoot",
    "th", "thead", "tr", "ul",
})
_WHITESPACE_RE = re.compile(r"\s")
# A card's words while the browser fills it in ("Loading image..."), or its status after: no
# note's text, and gone from the page once the card is drawn (search-highlight-service.js
# LOADING_PLACEHOLDER_CLASS). A placeholder holds text only.
_LOADING_PLACEHOLDER_CLASS = "note-loading-placeholder"
# A Mermaid diagram as stored: its code, which the browser swaps for the drawing. Neither is the
# note's text; the diagram is one stop when its code holds the words (find-in-list-service.js
# diagramStops; docs/ui/find.md, "Diagrams").
_DIAGRAM_SOURCE_CLASS = "meta-mermaid-source"
_DIAGRAM_SOURCE_TAG = "pre"
_DIAGRAM_WHITESPACE_RE = re.compile(r"\s+")
_WORD_CHARACTER_RE = re.compile(r"[^\W_]")


class _VisibleTextReader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ends_with_space = True
        # The tag of the placeholder being read, whose words are skipped; None outside one.
        self._placeholder_tag: str | None = None
        # Each diagram's code, in order; the one being read, and how deep in it the reader is.
        self.diagram_sources: list[str] = []
        self._diagram_parts: list[str] | None = None
        self._diagram_depth = 0

    def _add_space(self) -> None:
        if self._ends_with_space:
            return
        self.parts.append(" ")
        self._ends_with_space = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._diagram_parts is not None:
            self._diagram_depth += 1
            return
        if tag == _DIAGRAM_SOURCE_TAG and _DIAGRAM_SOURCE_CLASS in _classes_of(attrs):
            # Skipped whole, as the browser's reading skips the drawing: no break either.
            self._diagram_parts = []
            return
        if self._placeholder_tag is not None:
            raise ValueError(f"A loading placeholder holds text only, not a <{tag}>")
        # Skipped whole, as the browser's reading skips it: no break either.
        if _LOADING_PLACEHOLDER_CLASS in _classes_of(attrs):
            self._placeholder_tag = tag
            return
        if tag in _TEXT_BREAKING_ELEMENTS:
            self._add_space()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._diagram_parts is not None:
            return
        if tag in _TEXT_BREAKING_ELEMENTS:
            self._add_space()

    def handle_endtag(self, tag: str) -> None:
        if self._diagram_parts is not None:
            if self._diagram_depth > 0:
                self._diagram_depth -= 1
                return
            assert tag == _DIAGRAM_SOURCE_TAG, f"A diagram's code ended by </{tag}>"
            self.diagram_sources.append("".join(self._diagram_parts))
            self._diagram_parts = None
            return
        if self._placeholder_tag is not None:
            assert tag == self._placeholder_tag, f"A loading placeholder <{self._placeholder_tag}> ended by </{tag}>"
            self._placeholder_tag = None
            return
        if tag in _TEXT_BREAKING_ELEMENTS:
            self._add_space()

    def handle_data(self, data: str) -> None:
        if self._diagram_parts is not None:
            self._diagram_parts.append(data)
            return
        if self._placeholder_tag is not None:
            return
        for character in data:
            if _WHITESPACE_RE.match(character):
                self._add_space()
            else:
                self.parts.append(character)
                self._ends_with_space = False


def _classes_of(attrs: list[tuple[str, str | None]]) -> list[str]:
    for name, value in attrs:
        if name == "class" and value is not None:
            return value.split()
    return []


def read_visible_text(html: str) -> str:
    """An element's text as the browser's marks read it: every run of whitespace, and
    every break between blocks or lines, is one space."""
    return "".join(_read(html).parts)


def count_find_stops(html: str, find_text: str) -> int:
    """The stops find makes in a note's rendered HTML: each occurrence in its text, and each
    diagram whose code holds the find text once, however often (the page counts the same,
    find-in-list-service.js pageRangesFor)."""
    reader = _read(html)
    diagrams = sum(
        1 for source in reader.diagram_sources
        if count_occurrences(_DIAGRAM_WHITESPACE_RE.sub(" ", source).strip(), find_text) > 0
    )
    return count_occurrences("".join(reader.parts), find_text) + diagrams


def _read(html: str) -> _VisibleTextReader:
    if not isinstance(html, str):
        raise TypeError(f"html must be a string, got {type(html)}")
    reader = _VisibleTextReader()
    reader.feed(html)
    reader.close()
    assert reader._diagram_parts is None, "A diagram's code was never closed"
    return reader


def read_comment_text(comment: str) -> str:
    """A tag-bar comment's text as its element reads: whitespace runs are one space."""
    if not isinstance(comment, str):
        raise TypeError(f"comment must be a string, got {type(comment)}")
    reader = _VisibleTextReader()
    reader.handle_data(comment)
    return "".join(reader.parts)


def _lowercase_in_place(text: str) -> str:
    """Lowercase, one character for one, so a position in the result is the same
    position in the text (a letter whose lowercase is longer, such as İ, stays)."""
    lowered: list[str] = []
    for character in text:
        lower = character.lower()
        if len(lower) == len(character):
            lowered.append(lower)
        else:
            lowered.append(character)
    return "".join(lowered)


def _is_word_edge(text: str, index: int, is_required: bool) -> bool:
    if not is_required:
        return True
    if index < 0 or index >= len(text):
        return True
    return _WORD_CHARACTER_RE.match(text[index]) is None


def count_occurrences(text: str, find_text: str) -> int:
    """How often find_text occurs in text: in any case, also inside words and
    overlapping; a space at its edge limits it to a word edge on that side."""
    if not isinstance(text, str) or not isinstance(find_text, str):
        raise TypeError("count_occurrences requires strings")
    core = _lowercase_in_place(find_text.strip())
    if core == "":
        raise ValueError("The text to find must not be blank")
    word_starts = find_text.startswith(" ")
    word_ends = find_text.endswith(" ")
    lowered = _lowercase_in_place(text)
    count = 0
    start = lowered.find(core)
    while start != -1:
        end = start + len(core)
        if _is_word_edge(lowered, start - 1, word_starts) and _is_word_edge(lowered, end, word_ends):
            count += 1
        start = lowered.find(core, start + 1)
    return count
