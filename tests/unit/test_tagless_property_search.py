"""A property on any tag (docs/ui/search-syntax.md, Super Tag Searches; agreed 2026-10-25):
`:version` finds notes where any tag carries a version; values, comparisons, units, - and +
work as on a tag; `:version?` is refused; a bare `:` suggests the vault's property names."""

from __future__ import annotations

import pytest

from app.services.input_errors import InputRejected
from app.services.search_index import NOTHING_INHERITED, SearchIndex, SearchRecord, extract_tags_for_search
from app.services.search_query import parse_search_query


def _inherits_nothing(note_ids):
    """A search index alone has no note tree: its notes inherit no values."""
    return {note_id: NOTHING_INHERITED for note_id in note_ids}

NOTES = {
    "metalist-0245": "metalist:version=0.24.5",
    "metalist-0231": "metalist:version=0.23.1",
    "phone-app": "phone-app:version=2",
    "no-version": "metalist",
    "run": "jogging:miles=3",
    "walk": "walking:miles=5mi",
}


@pytest.fixture
def index() -> SearchIndex:
    search_index = SearchIndex()
    search_index.attach_inherited_values_reader(_inherits_nothing)
    search_index.rebuild(
        [SearchRecord(note_id=note_id, content_text="", tags=tags, tag_terms=extract_tags_for_search(tags))
         for note_id, tags in NOTES.items()],
        raw_tag_terms_by_id={note_id: extract_tags_for_search(tags) for note_id, tags in NOTES.items()},
        progress_update=lambda processed: None, progress_interval=len(NOTES),
    )
    return search_index


@pytest.mark.parametrize(("search", "found"), [
    (":version", {"metalist-0245", "metalist-0231", "phone-app"}),
    (":version=0.24.5", {"metalist-0245"}),
    (":version=2", {"phone-app"}),
    (":miles>4", {"walk"}),
    (":miles<=5mi", {"walk"}),
    ("metalist -:version", {"no-version"}),
    ("+:miles", {"run", "walk"}),
    # MAX compares within the kind most values are (here numbers: 3 and 5mi).
    (":miles=MAX", {"walk"}),
    (":version OR :miles<4", {"metalist-0245", "metalist-0231", "phone-app", "run"}),
    # A tag's own term is unchanged: only its own values.
    ("metalist:version", {"metalist-0245", "metalist-0231"}),
])
def test_a_property_on_any_tag(index: SearchIndex, search: str, found: set[str]) -> None:
    assert index.query_note_ids(search) == found


@pytest.mark.parametrize(("search", "message"), [
    (":version?", "A search for a missing property needs its tag (for example jogging:miles?)"),
    (":", "Name a property after the colon (for example :version=0.24)"),
])
def test_a_property_on_any_tag_says_how_to_write_it(search: str, message: str) -> None:
    with pytest.raises(InputRejected, match=message.replace("(", r"\(").replace(")", r"\)").replace("?", r"\?")):
        parse_search_query(search)


@pytest.mark.parametrize(("typed", "expected"), [
    # Names used on any tag, most used first, ties by name.
    (":", [(":version", "version"), (":miles", "miles")]),
    (":m", [(":miles", "miles")]),
    # Units after a number, from every tag with the property.
    (":miles<5m", [(":miles<5mi", "5mi")]),
    (":version=", [(":version=MAX", "MAX"), (":version=MIN", "MIN"),
                   (":version=0.23.1", "0.23.1"), (":version=0.24.5", "0.24.5"), (":version=2", "2")]),
])
def test_a_bare_colon_suggests_the_vaults_property_names(index: SearchIndex, typed: str, expected: list[tuple[str, str]]) -> None:
    suggestions = index.suggest_property_completions(typed=typed, place="search", limit=10)
    assert [(suggestion.replacement, suggestion.label) for suggestion in suggestions] == expected
