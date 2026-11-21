"""The lines of a note, offered after `#` in the list `[[` opens (docs/ui/references.md, "Links
to a place in a note"; the maintainer, 2026-11-21): `[[Trip plan#` lists the lines of Trip plan
and of the notes under it, headings first, narrowed by what is typed after the `#`. Choosing one
writes `[[UUID#that line]]`, a link that leads to those words in the note."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

from app.services.content_cache import get_cached_content
from app.services.content_formatting import find_global_credential_tag
from app.services.note_store import NoteRecord
from app.services.store import store
from app.services.structured_note_renderers import extract_plain_text_from_note_html

# A Markdown heading: its marks are not part of the words a link looks for.
_HEADING_RE = re.compile(r"^#{1,6}\s+(?P<text>.+)$")
# A note that is a heading as a whole (its first line).
_HEADING_TAG = "@heading"
# What a link's text can't hold: it would end the link, or start its shown text.
_NOT_IN_A_LINK_RE = re.compile(r"[\[\]|\n]")
# A long line is offered by its start: the link finds the line by those words.
MAX_LINE_CHARACTERS = 60
MAX_LINES_OFFERED = 20
# How many notes under the linked one are read for their lines.
MAX_NOTES_READ = 500
NO_NOTE = ""
_NOTE_ID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def note_named_by_id(typed: str) -> str:
    """The note whose id was typed before the `#` (a link already written, `[[UUID#`), NO_NOTE
    when the text is no id of a note in the vault."""
    if _NOTE_ID_RE.fullmatch(typed) is None or not store.contains(typed):
        return NO_NOTE
    return typed


def first_line_of(note_id: str) -> str:
    return extract_plain_text_from_note_html(get_cached_content(note_id)).split("\n")[0].strip()


@dataclass(frozen=True, slots=True)
class ReferenceLine:
    text: str
    is_heading: bool


@dataclass(frozen=True, slots=True)
class NoteLines:
    # The note the lines are of, NO_NOTE when what was typed before the # names none.
    note_id: str
    first_line: str
    lines: Tuple[ReferenceLine, ...]


def _link_text_of(line: str) -> str:
    """The line as a link can hold it: up to the first character a link can't hold, and to a
    whole word when it is long."""
    cut = _NOT_IN_A_LINK_RE.split(line, maxsplit=1)[0].strip()
    if len(cut) <= MAX_LINE_CHARACTERS:
        return cut
    words = cut[:MAX_LINE_CHARACTERS + 1].rsplit(" ", 1)
    return words[0].strip()


def _lines_of(record: NoteRecord, *, is_root: bool) -> List[ReferenceLine]:
    # A password or username is never offered as text to link to.
    if find_global_credential_tag(record.tags) is not None:
        return []
    is_heading_note = _HEADING_TAG in record.tags.split()
    found: List[ReferenceLine] = []
    lines = extract_plain_text_from_note_html(get_cached_content(record.id)).split("\n")
    for index, line in enumerate(lines):
        # The linked note's own first line is the note itself.
        if is_root and index == 0:
            continue
        stripped = line.strip()
        heading = _HEADING_RE.match(stripped)
        is_heading = heading is not None
        if heading is not None:
            stripped = heading["text"]
        if index == 0 and is_heading_note:
            is_heading = True
        text = _link_text_of(stripped)
        if text != "":
            found.append(ReferenceLine(text=text, is_heading=is_heading))
    return found


def note_lines(*, note_id: str, first_line: str, line_query: str) -> NoteLines:
    """The lines of the note and of the notes under it that hold line_query (capitals ignored;
    all of them for ''), headings first, each once, in the order they are read."""
    assert store.contains(note_id), "the lines are those of a note in the vault"
    wanted = " ".join(line_query.split()).casefold()
    headings: List[ReferenceLine] = []
    others: List[ReferenceLine] = []
    seen: set[str] = set()
    waiting = [note_id]
    notes_read = 0
    while waiting and notes_read < MAX_NOTES_READ:
        current = waiting.pop()
        notes_read += 1
        for line in _lines_of(store.get(current), is_root=current == note_id):
            key = line.text.casefold()
            if key in seen or wanted not in key:
                continue
            seen.add(key)
            if line.is_heading:
                headings.append(line)
            else:
                others.append(line)
        waiting.extend(reversed(store.children(current)))
    return NoteLines(note_id=note_id, first_line=first_line, lines=tuple([*headings, *others][:MAX_LINES_OFFERED]))
