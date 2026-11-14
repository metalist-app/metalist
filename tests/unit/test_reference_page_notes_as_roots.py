"""A search made only of note IDs, as every reference page's is, lists just those notes, each as a
root with the notes under it, as an embed of the note shows it: no parents, no grey bars for the
notes beside it (the maintainer, 2026-11-13; docs/ready-to-build/reference-cards.md, §3)."""
from __future__ import annotations

from typing import Dict, List, Optional

import pytest

import app.services.snapshot as snapshot
from app.services.snapshot import build_view_state, resolve_view_scope_membership
from tests.unit.snapshot_note_fixture import SnapshotTestNote as _Note

BAR = "10000000-0000-4000-8000-000000000001"
BAZ = "10000000-0000-4000-8000-000000000002"
BAZ_CHILD = "10000000-0000-4000-8000-000000000003"
QUX = "10000000-0000-4000-8000-000000000004"
OTHER_ROOT = "10000000-0000-4000-8000-000000000005"


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

    def list_note_ids(self) -> List[str]:
        return list(self._notes)

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


@pytest.fixture
def bar_and_baz(monkeypatch: pytest.MonkeyPatch) -> None:
    """bar > (BAZ > BAZ_CHILD, QUX), then OTHER_ROOT."""
    notes = {
        BAR: _Note(BAR, None, None, OTHER_ROOT, False, "<div>bar</div>", ""),
        BAZ: _Note(BAZ, BAR, None, QUX, False, "<div>BAZ</div>", ""),
        BAZ_CHILD: _Note(BAZ_CHILD, BAZ, None, None, False, "<div>under BAZ</div>", ""),
        QUX: _Note(QUX, BAR, BAZ, None, False, "<div>qux</div>", ""),
        OTHER_ROOT: _Note(OTHER_ROOT, None, BAR, None, False, "<div>other</div>", ""),
    }
    store = _FakeNoteStore(notes=notes, children_by_parent={
        None: [BAR, OTHER_ROOT], BAR: [BAZ, QUX], BAZ: [BAZ_CHILD],
    })
    monkeypatch.setattr(snapshot, "note_store", store)
    monkeypatch.setattr(snapshot, "search_index", _FakeSearchIndex())
    monkeypatch.setattr(snapshot, "get_all_locks", lambda: {})


def _shown(search: str, editing_note_id: str | None, *, is_page: bool) -> list[tuple[str, str | None]]:
    """Each note the list shows, with the note it shows under (None for a root), in order. A
    page shows no grey bars."""
    state = build_view_state(
        editing_note_id=editing_note_id, find_reveal_note_id=None, search=search,
        sort_mode="normal", date_filter=None, file_filter=None,
        client_known_note_ids=set(), previous_root_ids=[],
        visible_top_root_id=None, visible_bottom_root_id=None,
        is_untagged_view=False, start_at_list_end=False,
    )
    if is_page:
        for entry in state.structure:
            assert state.payloads[str(entry["id"])]["flags"]["searchRedacted"] is False
    return [(str(entry["id"]), entry["parentId"]) for entry in state.structure]


def test_a_linked_child_shows_as_a_root_with_its_children(bar_and_baz) -> None:
    assert _shown(BAZ, None, is_page=True) == [(BAZ, None), (BAZ_CHILD, BAZ)]
    assert _shown(f"[[{BAZ}]]", None, is_page=True) == [(BAZ, None), (BAZ_CHILD, BAZ)]


def test_several_linked_notes_show_in_the_searchs_order(bar_and_baz) -> None:
    assert _shown(f"{OTHER_ROOT} OR {BAZ}", None, is_page=True) == [(OTHER_ROOT, None), (BAZ, None), (BAZ_CHILD, BAZ)]
    assert _shown(f"{BAZ} OR {OTHER_ROOT}", None, is_page=True) == [(BAZ, None), (BAZ_CHILD, BAZ), (OTHER_ROOT, None)]


def test_a_linked_note_inside_another_shows_once_inside_it(bar_and_baz) -> None:
    assert _shown(f"{BAZ_CHILD} OR {BAZ}", None, is_page=True) == [(BAZ, None), (BAZ_CHILD, BAZ)]


def test_a_note_edited_under_a_linked_note_keeps_its_page(bar_and_baz) -> None:
    assert _shown(BAZ, BAZ_CHILD, is_page=True) == [(BAZ, None), (BAZ_CHILD, BAZ)]


def test_a_search_with_other_terms_still_shows_the_notes_above(bar_and_baz) -> None:
    shown = _shown(f"bar [[{BAZ}]]", None, is_page=False)
    assert (BAR, None) in shown


def test_the_ai_sees_the_notes_the_page_shows(bar_and_baz) -> None:
    scope = resolve_view_scope_membership(
        search=BAZ, sort_mode="normal", date_filter=None, file_filter=None, is_untagged_view=False,
    )

    assert scope.ordered_root_ids == (BAZ,)
    assert scope.allowed_note_ids == frozenset({BAZ, BAZ_CHILD})
    assert scope.matched_note_ids == frozenset({BAZ, BAZ_CHILD})
