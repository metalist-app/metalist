"""Searching the stats figures: @sum:calories>2000 and the same for @count, @avg, @min and
@max (docs/ui/search-semantics.md, Stats figures; agreed 2026-10-28). A term compares the
figure a note carrying that stats tag shows, counted as its footer counts."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.input_errors import InputRejected
from app.services.search_index import SearchIndex, SearchRecord, extract_tags_for_search
from app.services.search_query import parse_search_query
from app.services.subtree_stats import SUMMARY_KINDS, stats_figure_values
from app.services.tag_properties import STATS_TERM_TAGS, PropertyCondition
from app.usecases import search_context_tags

# A food log: days under it, meals under each day.
NOTES = {
    "log": "",
    "big-day": "@sum=calories @avg=calories",
    "big-breakfast": "meal:calories=1000",
    "big-dinner": "meal:calories=1400",
    "usual-day": "@sum=calories",
    "usual-lunch": "meal:calories=700",
    "usual-dinner": "meal:calories=800",
    "empty-day": "@sum=calories @avg=calories",
    "stats-day": "@stats",
    "stats-feast": "meal:calories=2400",
    "fat-day": "@sum=fat",
    "fat-breakfast": "butter:fat=12g",
    "fat-pill": "supplement:fat=500mg",
    "count-day": "@count=calories",
    "count-meal": "meal:calories=300",
    "count-snack": "snack:calories=lots",
    "bare-day": "journal @sum",
    "bare-feast": "meal:calories=3000",
    "bare-empty-day": "journal @sum",
}
CHILDREN = {
    "log": ["big-day", "usual-day", "empty-day", "stats-day", "fat-day", "count-day", "bare-day", "bare-empty-day"],
    "big-day": ["big-breakfast", "big-dinner"],
    "usual-day": ["usual-lunch", "usual-dinner"],
    "stats-day": ["stats-feast"],
    "fat-day": ["fat-breakfast", "fat-pill"],
    "count-day": ["count-meal", "count-snack"],
    "bare-day": ["bare-feast"],
}


@dataclass(frozen=True)
class _Note:
    tags: str


@dataclass(frozen=True)
class _Tree:
    """The note store's lookups over NOTES, and the index's for a property's use."""

    index: SearchIndex

    def get_note(self, note_id: str) -> _Note:
        return _Note(NOTES[note_id])

    def get_children(self, note_id: str) -> list[str]:
        if note_id in CHILDREN:
            return CHILDREN[note_id]
        return []

    def is_property_used(self, property_name: str) -> bool:
        return self.index.is_property_name_used(property_name)


@pytest.fixture
def index() -> SearchIndex:
    search_index = SearchIndex()
    search_index.rebuild(
        [SearchRecord(note_id=note_id, content_text="", tags=tags, tag_terms=extract_tags_for_search(tags))
         for note_id, tags in NOTES.items()],
        raw_tag_terms_by_id={note_id: extract_tags_for_search(tags) for note_id, tags in NOTES.items()},
        progress_update=lambda processed: None, progress_interval=len(NOTES),
    )
    tree = _Tree(index=search_index)

    def read(note_id: str, condition: PropertyCondition):
        return stats_figure_values(note_id=note_id, condition=condition, context=tree)

    search_index.attach_stats_reader(read)
    return search_index


@pytest.mark.parametrize(("search", "found"), [
    # Totals 2,400, 1,500 and 0 (an empty day's sum is 0).
    ("@sum:calories>2000", {"big-day", "bare-day"}),
    ("@sum:calories=0", {"empty-day"}),
    ("@sum:calories=MAX", {"bare-day"}),
    ("@sum:calories=MIN", {"empty-day"}),
    ("@sum:calories", {"big-day", "usual-day", "empty-day", "bare-day"}),
    ("@sum:calories -@sum:calories>2000", {"usual-day", "empty-day"}),
    ("@SUM:calories>2000", {"big-day", "bare-day"}),
    # A bare @sum shows every property with numbers under the note: the same figure.
    ("journal @sum:calories>2000", {"bare-day"}),
    # The empty day has no average: a dash never compares.
    ("@avg:calories<600", set()),
    ("@avg:calories>1000", {"big-day"}),
    # Units as for values.
    ("@sum:fat>10g", {"fat-day"}),
    ("@sum:fat>10", {"fat-day"}),
    ("@sum:fat>600mg", set()),
    ("@sum:calories>2000 OR @sum:fat>10g", {"big-day", "bare-day", "fat-day"}),
])
def test_a_stats_term_compares_the_figure_the_note_shows(index: SearchIndex, search: str, found: set[str]) -> None:
    assert index.query_note_ids(search) == found
    clause_found = set().union(*(index.query_clause_note_ids(clause) for clause in parse_search_query(search).clauses))
    assert clause_found == found


def test_only_notes_carrying_the_tag_for_the_property_match(index: SearchIndex) -> None:
    # The log above the days, and a day with @stats only (2,400 calories), never match.
    assert "log" not in index.query_note_ids("@sum:calories>0")
    assert "stats-day" not in index.query_note_ids("@sum:calories>2000")


def test_a_count_counts_the_notes_with_a_number(index: SearchIndex) -> None:
    # The snack's calories=lots is not a number, as in the footer.
    assert index.query_note_ids("@count:calories=1") == {"count-day"}
    assert index.query_note_ids("@count:calories>1") == set()


def test_a_note_without_the_figure_has_none(index: SearchIndex) -> None:
    condition = PropertyCondition(tag="@count", name="calories", operator=">", value_text="1")
    assert stats_figure_values(note_id="usual-day", condition=condition, context=_Tree(index=index)) is None


@pytest.mark.parametrize(("search", "message"), [
    ("@sum>2000", "Name the property after @sum"),
    ("@sum:calories?", "@sum always has a figure"),
    ("@sum:calories>lots", "Compare @sum with a number"),
])
def test_a_stats_term_without_a_property_or_a_number_is_refused_with_how_to_write_it(search: str, message: str) -> None:
    with pytest.raises(InputRejected, match=message):
        parse_search_query(search)


def test_the_meta_tag_itself_stays_a_tag_search(index: SearchIndex) -> None:
    assert index.query_note_ids("@sum=calories") == {"big-day", "usual-day", "empty-day"}


def test_a_note_added_in_a_stats_search_gets_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search_context_tags.search_index, "list_tag_frequencies", lambda: {})
    assert search_context_tags.ensure_tags_match_search_query(
        parent_id=None, content="", tags="", search_query="@sum:calories>2000",
    ) == ""


def test_after_a_stats_tag_the_properties_it_is_carried_for_are_suggested(index: SearchIndex) -> None:
    names = index.suggest_stats_completions(typed="@sum:", limit=8)
    assert [suggestion.replacement for suggestion in names] == ["@sum:calories", "@sum:fat"]
    assert [suggestion.label for suggestion in names] == ["calories", "fat"]
    assert [suggestion.label for suggestion in index.suggest_stats_completions(typed="@sum:f", limit=8)] == ["fat"]
    keywords = index.suggest_stats_completions(typed="@sum:calories=M", limit=8)
    assert [suggestion.replacement for suggestion in keywords] == ["@sum:calories=MAX", "@sum:calories=MIN"]


def test_search_reads_the_same_five_tags_as_the_footer() -> None:
    assert STATS_TERM_TAGS == frozenset(f"@{kind}" for kind in SUMMARY_KINDS)


def _index_of(notes: dict[str, str]) -> SearchIndex:
    search_index = SearchIndex()
    search_index.rebuild(
        [SearchRecord(note_id=note_id, content_text="", tags=tags, tag_terms=extract_tags_for_search(tags))
         for note_id, tags in notes.items()],
        raw_tag_terms_by_id={note_id: extract_tags_for_search(tags) for note_id, tags in notes.items()},
        progress_update=lambda processed: None, progress_interval=len(notes),
    )
    return search_index


@pytest.mark.parametrize("day_tags", ["journal @sum", "journal @stats", "journal"])
def test_with_no_note_tagged_for_a_property_the_vaults_number_properties_are_suggested(day_tags: str) -> None:
    # A journal whose days carry a bare @sum, @stats or nothing yet still offers calories
    # after `journal @sum:` (reported 2026-10-28); text-only properties are no figures.
    index = _index_of({
        "day": day_tags, "burger": "burger:calories=450", "dessert": "calories=700",
        "lunch": "meal:protein=30g", "mood": "mood:feeling=good",
    })
    names = index.suggest_stats_completions(typed="@sum:", limit=8)
    assert [suggestion.replacement for suggestion in names] == ["@sum:calories", "@sum:protein"]
    assert names[0].reasons == ("Numbers on 2 notes",)


def test_names_the_tag_is_carried_for_come_first() -> None:
    index = _index_of({
        "day": "@sum=fat", "a": "meal:calories=1", "b": "meal:calories=2", "c": "butter:fat=3",
    })
    assert [suggestion.label for suggestion in index.suggest_stats_completions(typed="@sum:", limit=8)] == ["fat", "calories"]
