"""The snippet under a file's card when a quoted phrase of the search is in the file's text
(docs/ready-to-build/folder-import-and-file-previews.md, "Searchable file text"; the snippet's
cases agreed 2026-11-01).

It is part of the note's drawn HTML, inside the card (clicking it does what clicking the card
does), so it comes and goes only with the list drawn for a search (interaction principle 2),
goes when the note is edited and comes back on Escape like the card, and the search highlight
marks its phrases as it marks a note's text (principle 5). Only embedded cards get one: a link
to a file runs inside a line of text.
"""

from __future__ import annotations

import html
import re
from typing import Iterable, Tuple

from app.services.file_text_search import file_texts

# An embedded file's card (embedded_references._render_file_body): its id, then its tooltip.
_EMBED_CARD_RE = re.compile(
    r'<button type="button" class="note-file-reference-link note-file-reference-link-embed" '
    r'data-file-ref-id="(?P<file_id>[^"]+)" title="(?P<title>[^"]*)">'
)
_CARD_END = "</button>"
# The text shown around the first match: this many characters before it, this many in all.
_CONTEXT_BEFORE = 70
_SNIPPET_LENGTH = 220
_ELLIPSIS = "…"
_WORD_EDGE = " "
_CUT_TOOLTIP = ". Search covers its first ~2,000 pages."


def with_file_text_snippets(rendered: str, phrases: Tuple[str, ...]) -> str:
    """rendered with a snippet inside each embedded card whose file's text holds a phrase, and
    the tooltip of a file whose text was cut saying how far search reaches."""
    if not phrases:
        return rendered
    loaded = file_texts.loaded_file_ids()
    pieces = []
    position = 0
    for card in _EMBED_CARD_RE.finditer(rendered):
        file_id = html.unescape(card.group("file_id"))
        if file_id not in loaded:
            continue
        end = rendered.index(_CARD_END, card.end())
        opening = card.group(0)
        if file_texts.is_cut(file_id):
            opening = opening.replace(f'title="{card.group("title")}"', f'title="{card.group("title")}{_CUT_TOOLTIP}"')
        snippet = file_text_snippet(file_id, phrases)
        inside = rendered[card.end():end]
        if snippet != "":
            inside = f'{inside}<span class="note-file-text-snippet">{html.escape(snippet)}</span>'
        pieces.append(rendered[position:card.start()])
        pieces.append(opening + inside)
        position = end
    pieces.append(rendered[position:])
    return "".join(pieces)


def file_text_snippet(file_id: str, phrases: Iterable[str]) -> str:
    """A line or two of the file's text around the first place a phrase is, cut at word edges
    with an ellipsis; "" when no phrase is in it."""
    matching = [phrase for phrase in phrases if file_texts.term_matches(file_id, phrase)]
    if not matching:
        return ""
    text = file_texts.text_of(file_id)
    starts = [found.start() for found in (_phrase_re(phrase).search(text) for phrase in matching) if found is not None]
    if not starts:
        return ""
    first = min(starts)
    start = max(0, first - _CONTEXT_BEFORE)
    end = min(len(text), start + _SNIPPET_LENGTH)
    snippet = text[start:end]
    if start > 0:
        # Begin at the next word: the cut word's rest is no help.
        snippet = _ELLIPSIS + snippet[snippet.find(_WORD_EDGE) + 1:]
    if end < len(text):
        snippet = snippet[:snippet.rfind(_WORD_EDGE)] + _ELLIPSIS
    return snippet


def _phrase_re(phrase: str) -> re.Pattern[str]:
    """The phrase in the text as search reads it: any case; a space at its edge needs a word edge."""
    core = re.escape(phrase.strip())
    if phrase.startswith(_WORD_EDGE):
        core = r"(?<!\w)" + core
    if phrase.endswith(_WORD_EDGE):
        core = core + r"(?!\w)"
    return re.compile(core, re.IGNORECASE)
