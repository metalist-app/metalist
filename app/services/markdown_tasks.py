"""Ticking a task in a Markdown note (docs/ui/content-formatting.md, Tasks; agreed
2026-10-31): a click on box N rewrites that task's [ ] to [x], or back, in the note's
stored text, and nothing else.

The boxes are numbered as the renderer draws them (markdown_task_lines) over the note's
plain text (extract_plain_text_from_note_html). The stored text is HTML, so the plain text
is read here again, character by character, remembering where each character came from;
the mark between the brackets is then replaced where it stands in the HTML.
"""

from __future__ import annotations

import html
import re
from typing import List, NamedTuple

from app.services.input_errors import InputRejected
from app.services.markdown_rendering import markdown_task_lines

# As structured_note_renderers._extract_plain_text reads note HTML: these start a line,
# these closing tags vanish, every other tag vanishes, an entity is its character, and a
# non-breaking space is a space.
_HTML_TOKEN_RE = re.compile(
    r"(?P<line_break><br\s*/?>|<div[^>]*>|<p[^>]*>)|(?P<tag><[^>]+>)|(?P<entity>&[#\w]+;)|(?P<char>[^<&]|[<&])",
    re.IGNORECASE | re.DOTALL,
)
_LINE_BREAK = "\n"
_NO_BREAK_SPACE = " "
# A task line: any quote marks, its list marker, then [ ] or [x] (markdown_rendering._TASK_RE).
_TASK_LINE_RE = re.compile(r"^\s*(?:>\s?)*\s*(?:[-+*]|\d+\.)\s+\[(?P<mark>[ xX])\]")
_TICKED_MARK = "x"
_EMPTY_MARK = " "
_CHANGED_MESSAGE = "This note changed since it was shown; try the box again."


class _PlainCharacter(NamedTuple):
    character: str
    # Where the character stands in the HTML; a line break starts there too.
    html_start: int
    html_end: int


def toggle_task_in_note_html(*, content_html: str, task_index: int, is_ticked: bool) -> str:
    """The note's HTML with task task_index ticked (is_ticked) or emptied. The box must show
    the opposite now; if the note changed under it, InputRejected says to try again."""
    if not isinstance(content_html, str):
        raise TypeError(f"content_html must be a string, got {type(content_html)}")
    if not isinstance(task_index, int) or task_index < 0:
        raise ValueError(f"task_index must be a non-negative integer, got {task_index!r}")
    characters = _plain_characters(content_html)
    plain_text = "".join(character.character for character in characters)
    leading_breaks = len(plain_text) - len(plain_text.lstrip(_LINE_BREAK))
    task_lines = markdown_task_lines(plain_text.strip(_LINE_BREAK))
    if task_index >= len(task_lines):
        raise InputRejected(_CHANGED_MESSAGE)
    line_start = _line_start(plain_text, leading_breaks=leading_breaks, line_index=task_lines[task_index])
    line_end = plain_text.find(_LINE_BREAK, line_start)
    if line_end == -1:
        line_end = len(plain_text)
    match = _TASK_LINE_RE.match(plain_text[line_start:line_end])
    if match is None:
        raise InputRejected(_CHANGED_MESSAGE)
    if (match.group("mark") != _EMPTY_MARK) == is_ticked:
        # Already as asked (a second click before the first one's redraw): say so.
        raise InputRejected(_CHANGED_MESSAGE)
    mark = characters[line_start + match.start("mark")]
    new_mark = _EMPTY_MARK
    if is_ticked:
        new_mark = _TICKED_MARK
    return content_html[: mark.html_start] + new_mark + content_html[mark.html_end :]


def _plain_characters(content_html: str) -> List[_PlainCharacter]:
    characters: List[_PlainCharacter] = []
    for token in _HTML_TOKEN_RE.finditer(content_html):
        if token.group("tag") is not None:
            continue
        if token.group("line_break") is not None:
            characters.append(_PlainCharacter(_LINE_BREAK, token.start(), token.start()))
            continue
        text = html.unescape(token.group(0)).replace(_NO_BREAK_SPACE, " ").replace("\r", "")
        for character in text:
            characters.append(_PlainCharacter(character, token.start(), token.end()))
    return characters


def _line_start(plain_text: str, *, leading_breaks: int, line_index: int) -> int:
    """Where line line_index of the stripped plain text starts in the unstripped one."""
    position = leading_breaks
    for _ in range(line_index):
        position = plain_text.index(_LINE_BREAK, position) + len(_LINE_BREAK)
    return position
