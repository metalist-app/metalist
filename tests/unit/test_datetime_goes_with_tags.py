"""`@datetime` offered because it goes with the note's tags (the maintainer, 2026-11-02): a
journal entry is dated, so a note tagged journal is offered `@datetime`, dated now or by the
date its text names, once, never with an earlier note's date. Other built-in tags are not
offered this way yet."""

from __future__ import annotations

from datetime import datetime

import pytest

import app.services.tag_suggestions as tag_suggestions_module
from app.services.note_store import store
from app.services.search_index import search_index
from app.services.tag_suggestions import suggest_tags_with_reasons_for_note
from app.usecases.create_note import apply_insert_note
from tests.unit.test_super_tag_last_values import live_database  # noqa: F401 (the fixture)

_LIMIT = 8
_NOW = datetime(2026, 11, 2, 9, 41)
_DATED_NOW = "@datetime=2026-11-02T09:41"
_DATETIME = "@datetime"


class _FixedNow(datetime):
    @classmethod
    def now(cls, *timezone):
        return _NOW


@pytest.fixture
def journal(live_database, monkeypatch):  # noqa: F811 (the fixture)
    monkeypatch.setattr(tag_suggestions_module, "datetime", _FixedNow)
    _note("mon-entry", tags="journal @datetime=2026-10-31T21:00", text="Quiet day", parent_id=None)
    _note("tue-entry", tags="journal @datetime=2026-11-01T22:10", text="Rain all day", parent_id=None)
    _note("groceries", tags="shopping", text="Milk", parent_id=None)
    return live_database


def _note(note_id: str, *, tags: str, text: str, parent_id: str | None) -> None:
    apply_insert_note(note_id, parent_id, None, None, "", content=f"<div>{text}</div>", tags=tags, proposed_tags="")


def _offered(note_id: str, *, typed: str) -> list[tuple[str, tuple[str, ...]]]:
    """The tag bar's suggestions with their reasons; it sends what is typed as its last token."""
    written = store.get_note(note_id).tags.split()
    explicit = written
    if typed != "":
        explicit = [*written, typed]
    return [(suggestion.tag, suggestion.reasons) for suggestion in suggest_tags_with_reasons_for_note(
        note_id=note_id, anchors=written, explicit_tags=explicit, prefix=typed,
        content_html=store.get_note(note_id).content, limit=_LIMIT,
    )]


def _tags(note_id: str, *, typed: str) -> list[str]:
    return [tag for tag, _reasons in _offered(note_id, typed=typed)]


def _dates(shown: list[str]) -> list[str]:
    return [tag for tag in shown if tag.casefold().startswith(_DATETIME)]


def test_a_journal_entry_is_offered_the_date_now(journal) -> None:
    _note("wed-entry", tags="journal", text="Long day at work", parent_id=None)

    offered = _offered("wed-entry", typed="")

    assert offered[0][0] == _DATED_NOW
    assert any("journal" in reason for reason in offered[0][1]), offered[0][1]


def test_a_date_in_the_text_comes_first_once(journal) -> None:
    _note("wed-entry", tags="journal", text="Dentist on Nov 5 at 4pm", parent_id=None)

    shown = _tags("wed-entry", typed="")

    assert shown[0] == "@datetime=2026-11-05T16:00"
    assert _dates(shown) == ["@datetime=2026-11-05T16:00"]


def test_it_is_offered_once_never_bare_or_with_an_earlier_date(journal) -> None:
    _note("wed-entry", tags="journal", text="Long day at work", parent_id=None)

    assert _dates(_tags("wed-entry", typed="")) == [_DATED_NOW]


@pytest.mark.parametrize("typed", ["d", "dat", "datetime"])
def test_typing_the_start_of_it_offers_it_first(journal, typed: str) -> None:
    # Typing d already listed it after the other built-in tags (@diff, @done); going with
    # journal puts it first, as on the empty bar.
    _note("wed-entry", tags="journal", text="Long day at work", parent_id=None)

    shown = _tags("wed-entry", typed=typed)

    assert shown[0] == _DATED_NOW
    assert _dates(shown) == [_DATED_NOW]


def test_typing_another_tag_does_not_offer_it(journal) -> None:
    _note("wed-entry", tags="journal", text="Long day at work", parent_id=None)

    assert _dates(_tags("wed-entry", typed="sh")) == []


def test_a_note_already_dated_is_not_offered_another(journal) -> None:
    _note("wed-entry", tags="journal @datetime=2026-11-02T08:00", text="Long day at work", parent_id=None)

    assert _dates(_tags("wed-entry", typed="")) == []


def test_a_tag_never_used_with_a_date_does_not_offer_it(journal) -> None:
    _note("more-groceries", tags="shopping", text="Eggs", parent_id=None)

    assert _dates(_tags("more-groceries", typed="")) == []


def test_typing_the_built_in_tag_still_offers_it_without_a_tag_that_goes_with_it(journal) -> None:
    _note("more-groceries", tags="shopping", text="Eggs", parent_id=None)

    assert _dates(_tags("more-groceries", typed="@d")) == [_DATED_NOW]


def test_a_tag_inherited_from_a_parent_does_not_offer_it(journal) -> None:
    _note("mon-detail", tags="", text="Lunch with Sam", parent_id="mon-entry")

    assert _dates(_tags("mon-detail", typed="")) == []


def test_other_built_in_tags_are_not_offered_for_going_with_a_tag(journal) -> None:
    _note("soup", tags="recipe @green", text="Leek soup", parent_id=None)
    _note("salad", tags="recipe @green", text="Bean salad", parent_id=None)
    _note("stew", tags="recipe", text="Lentil stew", parent_id=None)

    assert [tag for tag in _tags("stew", typed="") if tag.startswith("@")] == []


def test_the_search_box_is_unchanged(journal) -> None:
    offered = search_index.suggest_tag_completions(query="journal ", limit=_LIMIT, by_family=False)

    assert [term for term in offered if term.startswith("@")] == []
