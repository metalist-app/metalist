"""Chained conditions in one search term (docs/ui/search-semantics.md, Super Tag Searches;
decided 2026-10-31): `:foo="bar":baz>3` and `exercise:miles>2:duration<40` hold when one tag
on the note meets every condition, where separate terms may each be met by another tag."""

from __future__ import annotations

import pytest

import app.services.search_index as search_index_module
from app.services.input_errors import InputRejected
from app.services.search_index import NOTHING_INHERITED, SearchIndex, SearchRecord, extract_tags_for_search
from app.services.search_query import parse_search_query
from app.services.tag_ontology import OntologyParseError, compile_rules, parse_rules_text
from app.usecases.search_comment_autofill import compute_initial_tags_for_new_note


def _inherits_nothing(note_ids):
    """A search index alone has no note tree: its notes inherit no values."""
    return {note_id: NOTHING_INHERITED for note_id in note_ids}

NOTES = {
    "one-tag": "x:foo=bar:baz=5",
    "two-tags": "x:foo=bar y:baz=5",
    "low": "x:foo=bar:baz=2",
    "run": "jogging:miles=3:duration=30",
    "run-and-ride": "jogging:miles=3 cycling:duration=30",
    "messiah": 'book:title="Dune: Messiah":year=1969',
    "dune-old": "book:title=Dune:year=1950",
}


@pytest.fixture
def index(monkeypatch: pytest.MonkeyPatch) -> SearchIndex:
    ontology = compile_rules(
        rules=parse_rules_text(text="jogging => exercise\ncycling => exercise\n", filename="test"), filename="test",
    )
    monkeypatch.setattr(search_index_module, "get_ontology_if_ready", lambda: ontology)
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
    # 1. One tag meets both; separate terms may be met by two tags.
    (':foo="bar":baz>3', {"one-tag"}),
    (':foo="bar" :baz>3', {"one-tag", "two-tags"}),
    # 2. Through implications, still one tag.
    ("exercise:miles>2:duration<40", {"run"}),
    ("exercise:miles>2 exercise:duration<40", {"run", "run-and-ride"}),
    # 3. A quoted value and a comparison.
    ('book:title="Dune":year>1960', {"messiah"}),
    # 4. Excluded: only notes where one tag meets both are left out.
    ('x -:foo="bar":baz>3', {"two-tags", "low"}),
    # 5. A bare name in a chain: the property is there.
    ("jogging:miles>2:duration", {"run"}),
])
def test_a_chain_is_met_by_one_tag(index: SearchIndex, search: str, found: set[str]) -> None:
    assert index.query_note_ids(search) == found


def test_a_chain_formats_back_as_written() -> None:
    [condition] = parse_search_query('book:title="Dune":year>1960').first_clause.required_properties
    assert [link.format() for link in condition.links] == ['book:title="Dune"', "book:year>1960"]
    assert condition.format() == 'book:title="Dune":year>1960'


@pytest.mark.parametrize(("search", "message"), [
    ("jogging:miles>2:duration?", "Search a missing property in a term of its own"),
    ("jogging:miles>2:duration=MIN", "MIN goes in a term of its own"),
    ("jogging:miles>2:Miles<5", "Name each property once in a search term"),
    (":foo=1:foo=2", "Name each property once in a search term"),
    ("@sum:calories>2000:fat<10", "Compare one figure per term"),
])
def test_what_a_chain_cannot_hold_is_explained(search: str, message: str) -> None:
    with pytest.raises(InputRejected, match=message):
        parse_search_query(search)


def test_a_rule_keeps_one_property_per_condition() -> None:
    with pytest.raises(OntologyParseError, match="One property per condition in a rule"):
        parse_rules_text(text="jogging:miles>2:duration<40 => tempo\n", filename="test")


@pytest.mark.parametrize(("typed", "expected"), [
    # 6. After a chain's colon, names used with the tag, not those it has.
    ('book:title="Dune":', [('book:title="Dune":year', "year")]),
    # Values for the last condition; no MAX or MIN in a chain.
    ('book:title="Dune":year=', [('book:title="Dune":year=1950', "1950"), ('book:title="Dune":year=1969', "1969")]),
    (':foo="bar":b', [(':foo="bar":baz', "baz")]),
])
def test_suggestions_follow_the_last_condition(index: SearchIndex, typed: str, expected: list[tuple[str, str]]) -> None:
    suggestions = index.suggest_property_completions(typed=typed, place="search", limit=10)
    assert [(suggestion.replacement, suggestion.label) for suggestion in suggestions] == expected


def test_a_new_note_carries_every_value_of_a_chain() -> None:
    # 7. Each = gives its value; a comparison gives the tag alone (a child under a result).
    assert compute_initial_tags_for_new_note(parent_id=None, search_query="jogging:miles=3:duration=30") == (
        "jogging:miles=3:duration=30"
    )
    assert compute_initial_tags_for_new_note(parent_id=None, search_query="jogging:miles=3:duration>30") == (
        "jogging:miles=3"
    )
