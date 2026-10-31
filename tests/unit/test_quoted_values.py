"""Quoted tag values (docs/design/tag-properties.md, Quoted values; decided 2026-10-30): a
value in quotes holds spaces and any character, and every reader of tags, searches and
rules keeps it whole."""

from __future__ import annotations

from datetime import date

import pytest

from app.services.dictation_cleanup import clean_dictated_paste
from app.services.note_datetime import note_date_of_tags
from app.services.ontology_rules_store import _replace_tag_tokens_in_line
from app.services.quoted_values import (
    canonical_valued_token,
    has_open_value,
    is_closed_quoted_value,
    quote_value,
    split_tokens,
    unquote_value,
)
from app.services.search_index import SearchIndex, SearchRecord, extract_tags_for_search, tag_bar_values
from app.services.search_query import parse_search_query
from app.services.search_text import extract_tag_bar_comment_text
from app.services.tag_ontology import OntologyParseError, compile_rules, is_valid_proposal_token, parse_rules_text
from app.services.tag_rename import delete_tag_from_tag_bar, rename_tag_in_tag_bar
from app.usecases.search_comment_autofill import compute_initial_tags_for_new_note
from app.usecases.tag_proposals import _proposal_tokens

NOTES = {
    "le-guin": 'author="Ursula Le Guin" book:title="A Wizard of Earthsea":year=1968',
    "herbert": 'author=Herbert book:title="Dune: Messiah":year=1969',
    "best": 'title="The \\"Best\\" Book"',
    "obrien": "author=O'Brien",
    "bar": "baz:foo=bar",
    "bag": "zed:foo=bag",
    "aba": "x:foo=aba",
    "dashed": "zed:foo=asdf-jkl",
}


@pytest.fixture
def index() -> SearchIndex:
    search_index = SearchIndex()
    search_index.rebuild(
        [SearchRecord(note_id=note_id, content_text="", tags=tags, tag_terms=extract_tags_for_search(tags))
         for note_id, tags in NOTES.items()],
        raw_tag_terms_by_id={note_id: extract_tags_for_search(tags) for note_id, tags in NOTES.items()},
        progress_update=lambda processed: None, progress_interval=len(NOTES),
    )
    return search_index


def test_tokens_keep_a_quoted_value_whole() -> None:
    assert split_tokens('author="Ursula Le Guin" book:title="Dune: Messiah" sf') == [
        'author="Ursula Le Guin"', 'book:title="Dune: Messiah"', "sf",
    ]
    assert split_tokens('author "Ursula Le Guin"') == ["author", '"Ursula', "Le", 'Guin"']
    assert split_tokens("author='Brien x") == ["author='Brien", "x"]
    assert split_tokens('a="b c') == ['a="b c']


def test_a_value_reads_without_its_quotes_and_is_written_with_them_only_when_needed() -> None:
    assert unquote_value('"The \\"Best\\" Book"') == 'The "Best" Book'
    assert unquote_value('"a\\\\b"') == "a\\b"
    assert quote_value('The "Best" Book') == '"The \\"Best\\" Book"'
    assert quote_value("Ursula Le Guin") == '"Ursula Le Guin"'
    assert quote_value("asdf-jkl") == "asdf-jkl"
    assert quote_value("10:30pm") == "10:30pm"
    assert quote_value("Dune:Messiah") == '"Dune:Messiah"'
    assert canonical_valued_token('zed:foo="asdf-jkl"') == "zed:foo=asdf-jkl"
    assert canonical_valued_token('author="asdf-jkl"') == "author=asdf-jkl"
    assert canonical_valued_token('author="Le Guin"') == 'author="Le Guin"'


def test_open_and_closed_values() -> None:
    assert has_open_value('author="Ursula Le')
    assert not has_open_value('author="Ursula Le Guin" x')
    assert is_closed_quoted_value('"Le Guin"')
    assert not is_closed_quoted_value('"Le Guin')
    assert not is_closed_quoted_value('"Le"Guin')


def test_the_tag_bar_reads_a_quoted_value_as_one_tag() -> None:
    assert extract_tags_for_search('author="Ursula Le Guin" sf') == {'author="Ursula Le Guin"', "sf"}
    own_tags, values = tag_bar_values('book:title="Dune: Messiah":year=1969')
    assert own_tags == {"book"}
    assert values[("book", "title")].text == "Dune: Messiah"
    assert values[("book", "year")].text == "1969"


@pytest.mark.parametrize(("search", "found"), [
    ('author="Ursula Le Guin"', {"le-guin"}),
    # A quoted value is a text match inside the value; a bare one is exact.
    ('author="Ursula"', {"le-guin"}),
    ("author=Ursula", set()),
    ('book:title="A Wizard of Earthsea"', {"le-guin"}),
    ('book:title="Dune: Messiah"', {"herbert"}),
    ('book:title="messiah"', {"herbert"}),
    ('title="The \\"Best\\" Book"', {"best"}),
    ("author=O'Brien", {"obrien"}),
    (':foo="ba"', {"bar", "bag", "aba"}),
    (":foo=ba", set()),
    ('zed:foo="asdf-jkl"', {"dashed"}),
    ("zed:foo=asdf-jkl", {"dashed"}),
    ('book:year>"1968"', {"herbert"}),
])
def test_a_quoted_value_in_a_search(index: SearchIndex, search: str, found: set[str]) -> None:
    assert index.query_note_ids(search) == found


def test_a_tag_and_a_quoted_text_parted_by_a_space_stay_two_terms() -> None:
    clause = parse_search_query('author "Ursula Le Guin"').first_clause
    assert "author" in clause.required_tags
    assert clause.required_text == ("Ursula Le Guin",)
    assert clause.required_properties == ()


def test_a_rule_reads_a_quoted_value() -> None:
    [rule] = parse_rules_text(text='book:title="Wizard of" => earthsea\n', filename="test")
    assert rule.lhs[0].condition.format() == 'book:title="Wizard of"'
    ontology = compile_rules(rules=[rule], filename="test")
    own_tags, values = tag_bar_values(NOTES["le-guin"])
    assert ontology.infer_value_tags(values=values, own_tag_names=own_tags, base_tags=frozenset({"book"}),
                                     plaintext="") == {"earthsea"}
    with pytest.raises(OntologyParseError, match="Close the quoted value"):
        parse_rules_text(text='book:title="Wizard of => earthsea\n', filename="test")


def test_renaming_and_deleting_a_tag_keeps_quoted_values_whole() -> None:
    tags = 'book:title="A b c" x'
    assert rename_tag_in_tag_bar(tags=tags, old="book", new="novel") == ('novel:title="A b c" x', True)
    assert rename_tag_in_tag_bar(tags=tags, old="b", new="z") == (tags, False)
    assert delete_tag_from_tag_bar(tags=tags, tag="book") == (" x", True)
    assert _replace_tag_tokens_in_line(line='book:title="A (b)" => x', old="book", new="novel") == (
        'novel:title="A (b)" => x'
    )


def test_a_proposal_may_hold_a_quoted_value() -> None:
    assert is_valid_proposal_token('book:title="A Wizard of Earthsea"')
    assert not is_valid_proposal_token('book:title="A Wizard')
    assert not is_valid_proposal_token('book:title=""')
    assert not is_valid_proposal_token("book:title=A Wizard")
    assert _proposal_tokens('book:title="A Wizard of Earthsea" sf') == ('book:title="A Wizard of Earthsea"', "sf")


def test_a_pasted_quoted_value_is_one_tag() -> None:
    def clean(text: str, target: str) -> str:
        return clean_dictated_paste(
            text=text, target=target, existing_tag_frequencies={"fantasy": 1},
            current_value="", quote_open="quote", quote_close="end quote", negate_phrase="minus",
        )

    assert clean('author="Ursula Le Guin" fantasy', "tags") == 'author="Ursula Le Guin" fantasy'
    # A spoken quote around other words is still a quoted text.
    assert clean('book:title="A Wizard" quote big cat end quote', "search") == 'book:title="A Wizard" "big cat"'


def test_text_inside_a_quoted_value_is_neither_a_comment_nor_a_date() -> None:
    assert extract_tag_bar_comment_text('title="a /* b */" /*note*/') == "note"
    assert note_date_of_tags('title="moved @datetime=2026-01-01"') is None
    assert note_date_of_tags('title="x y" @datetime=2026-01-02') == date(2026, 1, 2)


def test_a_new_note_in_a_quoted_value_search_carries_the_value() -> None:
    assert compute_initial_tags_for_new_note(parent_id=None, search_query='book:author="Le Guin"') == (
        'book:author="Le Guin"'
    )
    assert compute_initial_tags_for_new_note(parent_id=None, search_query='author="Le Guin"') == 'author="Le Guin"'
    assert compute_initial_tags_for_new_note(parent_id=None, search_query="jogging:miles=3") == "jogging:miles=3"


@pytest.mark.parametrize(("typed", "place", "expected"), [
    # The values notes give the property, quoted when they need it; no MAX or MIN for text.
    ("book:title=", "search", [('book:title="A Wizard of Earthsea"', '"A Wizard of Earthsea"'),
                               ('book:title="Dune: Messiah"', '"Dune: Messiah"')]),
    ("book:title=", "tag-bar", [('book:title="A Wizard of Earthsea"', '"A Wizard of Earthsea"'),
                                ('book:title="Dune: Messiah"', '"Dune: Messiah"')]),
    # A bare partial matches a value's start, a quoted one anywhere in it.
    ("book:title=D", "search", [('book:title="Dune: Messiah"', '"Dune: Messiah"')]),
    ('book:title="wiz', "search", [('book:title="A Wizard of Earthsea"', '"A Wizard of Earthsea"')]),
    ("book:year=", "search", [("book:year=MAX", "MAX"), ("book:year=MIN", "MIN"),
                              ("book:year=1968", "1968"), ("book:year=1969", "1969")]),
])
def test_values_are_suggested_after_the_equals_sign(
    index: SearchIndex, typed: str, place: str, expected: list[tuple[str, str]],
) -> None:
    suggestions = index.suggest_property_completions(typed=typed, place=place, limit=10)
    assert [(suggestion.replacement, suggestion.label) for suggestion in suggestions] == expected
