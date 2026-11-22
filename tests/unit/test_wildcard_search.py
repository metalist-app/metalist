"""`*` in a search's tag term (docs/ui/search-semantics.md, Wildcards; agreed with the maintainer
2026-11-21, their note: "match tags using *, e.g. *burger*"): `*burger*` finds the notes with a
tag containing burger, `burger*` a tag starting with it, `*burger` one ending in it, capitals
ignored. Tags only; a new note is never given a wildcard as a tag."""
from __future__ import annotations

import pytest

from app.services.input_errors import InputRejected
from app.services.search_index import NOTHING_INHERITED, SearchIndex, SearchRecord, extract_tags_for_search
from app.services.search_query import is_wildcard_term, parse_search_query, tags_excluded_by_search, tags_named, wildcard_matches

_NOTES = {
    "plain": ("A burger", "burger"),
    "cheese": ("With cheese", "Cheeseburger lunch"),
    "night": ("Friday", "burger-night"),
    "veggie": ("Greens", "veggie-burgers"),
    "valued": ("Rated", "meal=hamburger"),
    "text only": ("I ate a burger today", "lunch"),
    "none": ("Soup", "soup"),
}


@pytest.fixture
def vault() -> SearchIndex:
    index = SearchIndex()
    index.attach_inherited_values_reader(lambda note_ids: {note_id: NOTHING_INHERITED for note_id in note_ids})
    index.rebuild(
        [SearchRecord(note_id=note_id, content_text=text, tags=tags, tag_terms=extract_tags_for_search(tags))
         for note_id, (text, tags) in _NOTES.items()],
        raw_tag_terms_by_id={note_id: extract_tags_for_search(tags) for note_id, (_text, tags) in _NOTES.items()},
        progress_update=lambda processed: None, progress_interval=len(_NOTES),
    )
    return index


@pytest.mark.parametrize(
    ("search", "found"),
    [
        # Without a star a tag is matched whole, as before.
        ("burger", {"plain"}),
        ("*burger*", {"plain", "cheese", "night", "veggie", "valued"}),
        ("burger*", {"plain", "night"}),
        ("*burger", {"plain", "cheese", "valued"}),
        ("*BURGER*", {"plain", "cheese", "night", "veggie", "valued"}),
        ("che*ger", {"cheese"}),
        # It narrows with the other terms, is left out with -, and joins with OR.
        ("*burger* lunch", {"cheese"}),
        ("-*burger*", {"text only", "none"}),
        ("lunch -*burger*", {"text only"}),
        ("*burger OR soup", {"plain", "cheese", "valued", "none"}),
        # A tag's value is part of the tag.
        ("meal=*", {"valued"}),
        # Tags only: a word in a note's text is not found.
        ("*ate*", set()),
        ("*nothing*", set()),
    ],
)
def test_a_star_stands_for_any_letters_of_a_tag(vault: SearchIndex, search: str, found: set[str]) -> None:
    assert vault.query_note_ids(search) == found


def test_a_term_of_stars_alone_is_refused() -> None:
    for search in ("*", "**", "lunch *", "-*"):
        with pytest.raises(InputRejected, match="letters"):
            parse_search_query(search)


def test_a_wildcard_is_told_from_a_tag_and_matched_whole() -> None:
    assert is_wildcard_term("*burger*") and not is_wildcard_term("burger")
    assert wildcard_matches("*burger*", "cheeseburger-night")
    assert wildcard_matches("burger*", "burger") and not wildcard_matches("burger*", "cheeseburger")
    # Every other character stands for itself.
    assert wildcard_matches("a.b*", "a.b-c") and not wildcard_matches("a.b*", "axb-c")


def test_a_wildcard_is_never_a_tag_the_search_excludes() -> None:
    # The empty tag bar leaves out tags a search excludes by name (tag_suggestions.py).
    assert tags_excluded_by_search("-*burger* -soup") == frozenset({"soup"})


def test_only_the_terms_that_name_a_tag_are_given_to_a_note() -> None:
    # A note made, moved or pasted under `lunch *burger*` gets lunch (search_context_tags.py).
    clause = parse_search_query("lunch *burger* -soup*").first_clause
    assert tags_named(sorted(clause.required_tags)) == ["lunch"]
    assert tags_named(clause.forbidden_tags) == []
