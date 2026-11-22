"""A long line shown by its first part (the maintainer, 2026-11-21: "if things are broken up by
a comma, or better yet a question mark, just have that portion"): the first sentence, or, when
that is still long or there is none, the part before the first comma. A link to a place in a
note reads this way (embedded_references.py); the text itself is never changed."""

from __future__ import annotations

import re

# A sentence's end, and a break inside one: each only before a space, so 3.5 and e.g.x stay whole.
_SENTENCE_END_RE = re.compile(r"[.?!]+(?=\s)")
_INNER_BREAK_RE = re.compile(r"[,;](?=\s)")
# A part shorter than this is no clause of its own ("e.g.", "Dr.", "Well,").
MIN_CLAUSE_CHARACTERS = 12
# A first sentence longer than this is cut at its first comma, when it has one.
LONG_CLAUSE_CHARACTERS = 40
# Marks that end a statement are dropped; a question or an exclamation keeps its mark.
_DROPPED_END_MARKS = ".,;"


def _cut_at_first(pattern: re.Pattern[str], text: str) -> str:
    for found in pattern.finditer(text):
        if found.start() >= MIN_CLAUSE_CHARACTERS:
            return text[:found.end()].rstrip(_DROPPED_END_MARKS)
    return text


def first_clause(text: str) -> str:
    """text by its first part, on one line ("galleries are confusing > only some pdfs
    displayed?"; no … after a cut part: the maintainer, 2026-11-21); text itself when it has no
    break worth cutting at."""
    whole = " ".join(text.split())
    part = _cut_at_first(_SENTENCE_END_RE, whole)
    if len(part) > LONG_CLAUSE_CHARACTERS:
        part = _cut_at_first(_INNER_BREAK_RE, part)
    return part
