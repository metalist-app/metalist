"""How a quoted search term matches text: note text (search_text.py) and a quoted property
value in a search (`:foo="ba"`, tag_properties.value_satisfies; docs/ui/search-semantics.md).
Kept apart so tag_properties can use it without importing the note renderer."""

from __future__ import annotations


def text_term_matches(term: str, text_casefold: str) -> bool:
    """Whether a quoted search term occurs in casefolded note text.

    A term matches anywhere, also inside words ("fat" in "father"), except that a
    space at its edge marks a word boundary on that side: "fat " needs the word to
    end there (a space, punctuation or the end of the text follows), " fat" needs it
    to start there (docs/ui/search-semantics.md).
    """
    if not isinstance(term, str) or not isinstance(text_casefold, str):
        raise TypeError("text_term_matches requires strings")
    core = term.strip().casefold()
    if core == "":
        raise ValueError("A quoted search term must not be blank")
    word_starts = term.startswith(" ")
    word_ends = term.endswith(" ")
    if not word_starts and not word_ends:
        return core in text_casefold
    start = text_casefold.find(core)
    while start != -1:
        end = start + len(core)
        if _is_word_edge(text_casefold, start - 1, word_starts) and _is_word_edge(text_casefold, end, word_ends):
            return True
        start = text_casefold.find(core, start + 1)
    return False


def _is_word_edge(text: str, index: int, required: bool) -> bool:
    """Whether position `index` (just outside a match) ends a word, when required."""
    if not required:
        return True
    if index < 0 or index >= len(text):
        return True
    return not text[index].isalnum()
