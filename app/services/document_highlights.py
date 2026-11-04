"""Word's highlight colours, as the file viewer shows a document's highlights (the maintainer,
2026-11-03: a .doc highlighted in colours showed plain): <mark class="file-highlight-NAME">, NAME
one of Word's 16 and nothing else of a file's style. The readers (document_text.py, the Word
reader's style map in file_view.py) write them; the viewer's sanitizer
(note_html.sanitize_viewed_document_html) and the rendered-HTML pass let these classes through,
and file-viewer.css colours them. Imports nothing: the file text worker reads documents too."""

from __future__ import annotations

from typing import Tuple

HIGHLIGHT_CLASS_PREFIX = "file-highlight-"
NO_HIGHLIGHT = ""

# The shades Word's highlights are drawn in, for each of red, green and blue.
_NONE = 0
_HALF = 128
_LIGHT = 192
_FULL = 255
# Word's 16, in the order a .doc numbers them (sprmCHighlight's ico, 1 to 16), with the colour
# each is drawn in (the nearest one stands for an RTF's colour).
WORD_HIGHLIGHTS: Tuple[Tuple[str, Tuple[int, int, int]], ...] = (
    ("black", (_NONE, _NONE, _NONE)),
    ("blue", (_NONE, _NONE, _FULL)),
    ("cyan", (_NONE, _FULL, _FULL)),
    ("green", (_NONE, _FULL, _NONE)),
    ("magenta", (_FULL, _NONE, _FULL)),
    ("red", (_FULL, _NONE, _NONE)),
    ("yellow", (_FULL, _FULL, _NONE)),
    ("white", (_FULL, _FULL, _FULL)),
    ("dark-blue", (_NONE, _NONE, _HALF)),
    ("dark-cyan", (_NONE, _HALF, _HALF)),
    ("dark-green", (_NONE, _HALF, _NONE)),
    ("dark-magenta", (_HALF, _NONE, _HALF)),
    ("dark-red", (_HALF, _NONE, _NONE)),
    ("dark-yellow", (_HALF, _HALF, _NONE)),
    ("dark-gray", (_HALF, _HALF, _HALF)),
    ("light-gray", (_LIGHT, _LIGHT, _LIGHT)),
)
HIGHLIGHT_NAMES = tuple(name for name, _colour in WORD_HIGHLIGHTS)
HIGHLIGHT_CLASSES = frozenset(HIGHLIGHT_CLASS_PREFIX + name for name in HIGHLIGHT_NAMES)
# A .docx names them as Word does (w:highlight w:val): darkCyan is dark-cyan.
DOCX_HIGHLIGHT_NAMES = {
    "black": "black", "blue": "blue", "cyan": "cyan", "green": "green", "magenta": "magenta", "red": "red",
    "yellow": "yellow", "white": "white", "darkBlue": "dark-blue", "darkCyan": "dark-cyan", "darkGreen": "dark-green",
    "darkMagenta": "dark-magenta", "darkRed": "dark-red", "darkYellow": "dark-yellow", "darkGray": "dark-gray",
    "lightGray": "light-gray",
}
assert set(DOCX_HIGHLIGHT_NAMES.values()) == set(HIGHLIGHT_NAMES)
FIRST_WORD_HIGHLIGHT_NUMBER = 1


def highlight_of_number(number: int) -> str:
    """The highlight a .doc numbers so (1 to 16); NO_HIGHLIGHT for 0 (none) or a number Word
    doesn't use."""
    index = number - FIRST_WORD_HIGHLIGHT_NUMBER
    if not 0 <= index < len(WORD_HIGHLIGHTS):
        return NO_HIGHLIGHT
    return WORD_HIGHLIGHTS[index][0]


def highlight_of_colour(colour: Tuple[int, ...]) -> str:
    """The highlight drawn nearest to an RGB colour (an RTF gives its highlights as colours)."""
    assert len(colour) == len(WORD_HIGHLIGHTS[0][1]), "a colour is red, green and blue"
    return min(
        WORD_HIGHLIGHTS,
        key=lambda highlight: sum((wanted - given) * (wanted - given) for wanted, given in zip(highlight[1], colour)),
    )[0]
