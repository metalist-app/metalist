from __future__ import annotations

from typing import Dict, List, Optional

import pytest

from app.services.snapshot import build_view_state
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
        return list(self._children_by_parent.get(parent_id, []))

    def get_inherited_non_meta_tag_terms(self, note_id: str) -> frozenset[str]:
        assert note_id in self._notes
        return frozenset()


class _FakeSearchIndex:
    def query_clause_note_ids(self, clause: object) -> set[str]:
        del clause
        return set()

    def is_property_name_used(self, property_name: str) -> bool:
        del property_name
        return False


def test_search_with_uuid_target_includes_direct_note_and_descendants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    notes = {
        "root": _Note("root", None, None, None, False, "<div>root</div>", ""),
        target_id: _Note(target_id, "root", None, "sibling", False, "<div>target</div>", ""),
        "target-child": _Note("target-child", target_id, None, None, False, "<div>child</div>", ""),
        "sibling": _Note("sibling", "root", target_id, None, False, "<div>sibling</div>", ""),
    }
    store = _FakeNoteStore(
        notes=notes,
        children_by_parent={
            None: ["root"],
            "root": [target_id, "sibling"],
            target_id: ["target-child"],
        },
    )

    import app.services.snapshot as snapshot

    monkeypatch.setattr(snapshot, "note_store", store)
    monkeypatch.setattr(snapshot, "search_index", _FakeSearchIndex())
    monkeypatch.setattr(snapshot, "get_all_locks", lambda: {})

    state = build_view_state(
        editing_note_id=None, find_reveal_note_id=None,
        search=f"[[{target_id}]]",
        sort_mode="normal", date_filter=None, file_filter=None,
        client_known_note_ids=set(), previous_root_ids=[],
        visible_top_root_id=None,
        visible_bottom_root_id=None,
        is_untagged_view=False,
        start_at_list_end=False,
    )

    assert state.payloads["root"]["flags"]["searchRedacted"] is False
    assert state.payloads[target_id]["flags"]["searchRedacted"] is False
    assert state.payloads["target-child"]["flags"]["searchRedacted"] is False
    assert state.payloads["sibling"]["flags"]["searchRedacted"] is True


class _StatsSearchIndex(_FakeSearchIndex):
    """The index answering @sum:calories>2000 with the big day."""

    def query_clause_note_ids(self, clause: object) -> set[str]:
        del clause
        return {"big-day"}


def test_a_note_found_by_a_stats_search_shows_its_children(monkeypatch: pytest.MonkeyPatch) -> None:
    # As a tag search shows a found note's children (they inherit its tags), a day found by
    # its calorie total shows the meals that make it up (agreed 2026-10-28).
    notes = {
        "log": _Note("log", None, None, None, False, "<div>log</div>", ""),
        "big-day": _Note("big-day", "log", None, "small-day", False, "<div>big</div>", "@sum=calories"),
        "dinner": _Note("dinner", "big-day", None, None, False, "<div>dinner</div>", "meal:calories=2400"),
        "small-day": _Note("small-day", "log", "big-day", None, False, "<div>small</div>", "@sum=calories"),
        "lunch": _Note("lunch", "small-day", None, None, False, "<div>lunch</div>", "meal:calories=500"),
    }
    store = _FakeNoteStore(
        notes=notes,
        children_by_parent={None: ["log"], "log": ["big-day", "small-day"], "big-day": ["dinner"], "small-day": ["lunch"]},
    )

    import app.services.snapshot as snapshot

    monkeypatch.setattr(snapshot, "note_store", store)
    monkeypatch.setattr(snapshot, "search_index", _StatsSearchIndex())
    monkeypatch.setattr(snapshot, "get_all_locks", lambda: {})

    state = build_view_state(
        editing_note_id=None, find_reveal_note_id=None,
        search="@sum:calories>2000",
        sort_mode="normal", date_filter=None, file_filter=None,
        client_known_note_ids=set(), previous_root_ids=[],
        visible_top_root_id=None,
        visible_bottom_root_id=None,
        is_untagged_view=False,
        start_at_list_end=False,
    )

    redacted = {note_id: state.payloads[note_id]["flags"]["searchRedacted"] for note_id in notes}
    assert redacted == {"log": False, "big-day": False, "dinner": False, "small-day": True, "lunch": True}
