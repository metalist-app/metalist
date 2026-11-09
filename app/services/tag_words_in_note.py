"""Words of a note's text the tag bar can offer as brand new tags (docs/ui/tag-bar.md, "Tag
Suggestions"): `yel` offers `Yellowstone` once no existing tag matches what is typed.

One word by default; a connector typed after a whole word asks for the next word as well
(`old-` offers `old-faithful`, `old_` offers `old_faithful`). The tag takes the case typing
started in (`yel` offers `yellowstone`, `Yel` offers `Yellowstone`).
"""

from __future__ import annotations

import re
from typing import Dict, List, Sequence, Tuple

from app.config import TAG_SUGGESTION_CONNECTORS

_CONNECTOR_CLASS = f"[{re.escape(TAG_SUGGESTION_CONNECTORS)}]"
_CONNECTOR_RE = re.compile(_CONNECTOR_CLASS)
_WORD_RE = re.compile(r"[^\W_]+(?:'[^\W_]+)*")
_POSSESSIVE_RE = re.compile(r"'s$", re.IGNORECASE)
# Two words are next to each other across spaces on one line, or one connector. A comma or
# a new line between them means they are not one name.
_WORD_GAP_RE = re.compile(rf"[^\S\r\n]+|{_CONNECTOR_CLASS}")


def _runs_of_adjacent_words(text: str) -> List[List[str]]:
    """The text's words, grouped into runs that follow each other with nothing between."""
    straight = text.replace("’", "'")
    runs: List[List[str]] = []
    previous_end = 0
    for match in _WORD_RE.finditer(straight):
        word = _POSSESSIVE_RE.sub("", match.group(0))
        if runs and _WORD_GAP_RE.fullmatch(straight[previous_end:match.start()]):
            runs[-1].append(word)
        else:
            runs.append([word])
        previous_end = match.end()
    return runs


def _typing_leads_to(words: Sequence[str], typed_words: Sequence[str]) -> bool:
    """Whether the typed words are these words, the last of them only begun."""
    assert len(words) == len(typed_words), (words, typed_words)
    finished = all(word.casefold() == typed.casefold() for word, typed in zip(words[:-1], typed_words[:-1]))
    return finished and words[-1].casefold().startswith(typed_words[-1].casefold())


def _in_case_typed(words: Sequence[str], typed_words: Sequence[str]) -> List[str]:
    """The words in the case typing started in: all small, all capitals (at least two typed,
    since one capital only starts a word), or else the letters typed and the note's for the rest."""
    typed = "".join(typed_words)
    if typed == typed.lower():
        return [word.lower() for word in words]
    if typed == typed.upper() and sum(character.isalpha() for character in typed) > 1:
        return [word.upper() for word in words]
    return [typed_word + word[len(typed_word):] for word, typed_word in zip(words, typed_words)]


def tags_from_words(*, typed: str, text: str, limit: int) -> Tuple[str, ...]:
    """What typing `typed` can complete to from the text, in the text's order and the case
    typed, joined with the connectors typed. What is already typed in full is not offered."""
    assert typed != "", "with nothing typed no word is asked for"
    typed_words = _CONNECTOR_RE.split(typed)
    connectors = _CONNECTOR_RE.findall(typed)
    word_count = len(typed_words)
    offered: Dict[str, str] = {}
    for run in _runs_of_adjacent_words(text):
        for start in range(len(run) - word_count + 1):
            words = run[start:start + word_count]
            if not _typing_leads_to(words, typed_words):
                continue
            cased = _in_case_typed(words, typed_words)
            tag = cased[0] + "".join(connector + word for connector, word in zip(connectors, cased[1:]))
            if tag.casefold() == typed.casefold():
                continue
            if tag.casefold() not in offered:
                offered[tag.casefold()] = tag
            if len(offered) == limit:
                return tuple(offered.values())
    return tuple(offered.values())
