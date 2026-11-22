"""A floating window's notes (docs/ui/state-handling.md, "Floating note windows"): its note and
the notes under it as the list draws them, folded as saved; a note edited there drawn for
editing, the notes above it open."""

from __future__ import annotations

from typing import Dict, List, Optional

import pytest

import app.services.snapshot as snapshot
from app.services.search_index import SearchIndex
from app.services.snapshot import build_window_state, is_in_window
from tests.unit.snapshot_note_fixture import SnapshotTestNote as _Note


class _FakeNoteStore:
    def __init__(self, *, notes: Dict[str, _Note], children_by_parent: Dict[Optional[str], List[str]]):
        self._notes = notes
        self._children_by_parent = children_by_parent

    def has_backlinks(self, note_id: str) -> bool:
        return False

    def has_note(self, note_id: str) -> bool:
        return note_id in self._notes

    def get_note(self, note_id: str) -> _Note:
        return self._notes[note_id]

    def get_children(self, parent_id: Optional[str]) -> List[str]:
        if parent_id in self._children_by_parent:
            return list(self._children_by_parent[parent_id])
        return []

    def get_inherited_non_meta_tag_terms(self, note_id: str) -> frozenset[str]:
        assert note_id in self._notes
        return frozenset()


@pytest.fixture
def trip_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    # "Trip plan" (folded in the list) holds "Tickets", which holds "Train"; "Groceries" is apart.
    notes = {
        "trip": _Note("trip", None, None, "groceries", True, "<div>Trip plan</div>", "travel"),
        "tickets": _Note("tickets", "trip", None, None, False, "<div>Tickets</div>", ""),
        "train": _Note("train", "tickets", None, None, False, "<div>Train <b>9:40</b></div>", ""),
        "groceries": _Note("groceries", None, "trip", None, False, "<div>Groceries</div>", ""),
    }
    store = _FakeNoteStore(notes=notes, children_by_parent={None: ["trip", "groceries"], "trip": ["tickets"], "tickets": ["train"]})
    monkeypatch.setattr(snapshot, "note_store", store)
    monkeypatch.setattr(snapshot, "search_index", SearchIndex())


def _shown(state) -> list[tuple[str, object]]:
    return [(entry["id"], entry["parentId"]) for entry in state.structure]


def test_the_window_shows_its_notes_folded_as_saved(trip_plan: None) -> None:
    # "Trip plan" is folded: the window shows it alone, folded, as the list does.
    state = build_window_state(window_note_id="trip", editing_note_id=None)
    assert _shown(state) == [("trip", None)]
    assert state.payloads["trip"]["flags"]["isCollapsed"] is True


def test_an_open_note_shows_the_notes_under_it(trip_plan: None) -> None:
    state = build_window_state(window_note_id="tickets", editing_note_id=None)
    assert _shown(state) == [("tickets", None), ("train", "tickets")]


def test_a_note_edited_in_the_window_opens_the_notes_above_it(trip_plan: None) -> None:
    state = build_window_state(window_note_id="trip", editing_note_id="train")
    assert _shown(state) == [("trip", None), ("tickets", "trip"), ("train", "tickets")]
    assert state.payloads["train"]["flags"]["isEditing"] is True
    assert state.payloads["train"]["content"] == "<div>Train <b>9:40</b></div>"
    assert state.payloads["trip"]["flags"]["isEditing"] is False
    assert state.payloads["trip"]["flags"]["isCollapsed"] is False


def test_a_note_outside_the_window_is_not_in_it(trip_plan: None) -> None:
    assert is_in_window(window_note_id="trip", note_id="train") is True
    assert is_in_window(window_note_id="trip", note_id="trip") is True
    assert is_in_window(window_note_id="trip", note_id="groceries") is False
    with pytest.raises(ValueError, match="not in the window"):
        build_window_state(window_note_id="trip", editing_note_id="groceries")
