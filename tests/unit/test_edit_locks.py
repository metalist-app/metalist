"""One editor per root note (multi-view editing step 4; docs/design/multi-view-editing.md,
"Step 4's cases"): a view editing any note under a root holds that root, and every other view's
change to it is refused at the note writes, while moving the root among the roots stays open."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pytest

import app.services.edit_locks as edit_locks_module
from app.db import notes_sql
from app.services.edit_locks import (
    HANDOVER_SECONDS, IN_ANOTHER_TAB, LEASE_SECONDS, ON_ANOTHER_COMPUTER, ON_YOUR_PHONE, SEARCH_LOCK_SECONDS,
    ComposerLockedElsewhere, NoteLockedElsewhere, SearchLockedElsewhere, edit_locks,
)

MAC = "view-mac"
MAC_TAB_TWO = "view-mac-second-tab"
PHONE = "view-phone"
MAC_BROWSER = "mac-sign-in"
PHONE_BROWSER = "phone-sign-in"
DESKTOP_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Safari/605.1.15"
PHONE_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
ROOT = "root-r"
CHILD = "child-of-r"
OTHER_ROOT = "root-s"
TAB = "search-context-1"
NOW = 1000.0


@dataclass
class _Record:
    id: str
    parent_id: Optional[str]


class _Tree:
    def __init__(self) -> None:
        self.notes = {
            ROOT: _Record(ROOT, None), CHILD: _Record(CHILD, ROOT), OTHER_ROOT: _Record(OTHER_ROOT, None),
        }

    def get_note(self, note_id: str) -> _Record:
        return self.notes[note_id]

    def has_note(self, note_id: str) -> bool:
        return note_id in self.notes


class _Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    edit_locks.reset()
    monkeypatch.setattr(edit_locks_module._Notes, "tree", _Tree())
    ticking = _Clock()
    monkeypatch.setattr(edit_locks_module, "monotonic", ticking)
    for view, browser, agent in ((MAC, MAC_BROWSER, DESKTOP_AGENT), (MAC_TAB_TWO, MAC_BROWSER, DESKTOP_AGENT),
                                 (PHONE, PHONE_BROWSER, PHONE_AGENT)):
        edit_locks.heard_from(view_id=view, token=browser, user_agent=agent)
    yield ticking
    edit_locks.reset()


class _As:
    """A request of this view: its writes are checked as its own."""

    def __init__(self, view_id: str, browser: str, agent: str) -> None:
        self.args = {"view_id": view_id, "token": browser, "user_agent": agent}

    def __enter__(self) -> None:
        self.entered = edit_locks.enter_request(**self.args)

    def __exit__(self, *_exc: object) -> None:
        edit_locks.leave_request(self.entered)


def as_mac() -> _As:
    return _As(MAC, MAC_BROWSER, DESKTOP_AGENT)


def as_phone() -> _As:
    return _As(PHONE, PHONE_BROWSER, PHONE_AGENT)


def _mac_edits_the_child() -> None:
    assert edit_locks.sync_editing(view_id=MAC, note_id=CHILD, tells_taken=True) == {}


def _notes_table() -> sqlite3.Connection:
    """Where an allowed write lands: the columns a save writes."""
    connection = sqlite3.connect(":memory:")
    connection.execute(f"CREATE TABLE {notes_sql.NOTES_TABLE} (id TEXT, content TEXT, updated_at TEXT)")
    return connection


def _save(note_id: str) -> None:
    notes_sql.update_note_fields(_notes_table(), note_id, updated_at=datetime.now(timezone.utc), content="typed")


def test_editing_a_child_locks_its_whole_root_for_the_other_views() -> None:
    _mac_edits_the_child()

    with as_phone(), pytest.raises(NoteLockedElsewhere) as refused:
        _save(ROOT)
    assert refused.value.root_id == ROOT and refused.value.where == ON_ANOTHER_COMPUTER
    assert edit_locks.locked_roots_for(view_id=PHONE) == {ROOT: ON_ANOTHER_COMPUTER}
    assert edit_locks.sync_editing(view_id=PHONE, note_id=ROOT, tells_taken=True) == {
        "rootId": ROOT, "lockedWhere": ON_ANOTHER_COMPUTER,
    }


def test_the_marker_says_where_the_root_is_being_edited() -> None:
    edit_locks.sync_editing(view_id=PHONE, note_id=ROOT, tells_taken=True)

    assert edit_locks.locked_roots_for(view_id=MAC) == {ROOT: ON_YOUR_PHONE}
    edit_locks.sync_editing(view_id=PHONE, note_id="", tells_taken=True)
    edit_locks.sync_editing(view_id=MAC_TAB_TWO, note_id=ROOT, tells_taken=True)
    assert edit_locks.locked_roots_for(view_id=MAC) == {ROOT: IN_ANOTHER_TAB}


def test_the_editing_view_writes_freely_and_other_roots_stay_open() -> None:
    _mac_edits_the_child()

    with as_mac():
        _save(CHILD)
    with as_phone():
        _save(OTHER_ROOT)


def test_collapsing_deleting_or_adding_under_a_locked_root_is_refused() -> None:
    _mac_edits_the_child()

    with as_phone():
        with pytest.raises(NoteLockedElsewhere):
            notes_sql.update_links_preserving_updated_at(None, ROOT, is_collapsed=True)
        with pytest.raises(NoteLockedElsewhere):
            notes_sql.delete_notes(None, [ROOT])
        with pytest.raises(NoteLockedElsewhere):
            notes_sql.update_links_preserving_updated_at(None, OTHER_ROOT, parent_id=CHILD, prev_id=None, next_id=None)
        with pytest.raises(NoteLockedElsewhere):
            notes_sql.update_links_preserving_updated_at(None, CHILD, parent_id=None, prev_id=None, next_id=None)
        with pytest.raises(NoteLockedElsewhere):
            notes_sql.update_links_preserving_updated_at(None, ROOT, parent_id=OTHER_ROOT, prev_id=None, next_id=None)


def test_moving_a_locked_root_among_the_roots_stays_open_and_is_kept_in_place_for_its_editor() -> None:
    _mac_edits_the_child()

    with as_phone():
        # Inside a transaction a write's own SQL runs after the check; the check is what is tested.
        # The moved note's own write names its parent too (app/usecases/move.py, apply_move).
        edit_locks.require_links_writable(note_id=ROOT, changes={"parent_id": None, "prev_id": OTHER_ROOT, "next_id": None})
        edit_locks.require_links_writable(note_id=OTHER_ROOT, changes={"next_id": ROOT})

    assert edit_locks.was_moved_elsewhere(root_id=ROOT)


def test_a_note_moved_next_to_the_edited_root_is_no_move_of_that_root() -> None:
    # Found 2026-11-15 (the maintainer): another view moved a note from below the edited root to
    # just above it; the editor's list kept the old order until editing ended, as if the edited
    # root had been moved and were being kept in place.
    _mac_edits_the_child()

    with as_phone():
        edit_locks.require_links_writable(note_id=OTHER_ROOT, changes={"parent_id": None, "prev_id": None, "next_id": ROOT})
        edit_locks.require_links_writable(note_id=ROOT, changes={"prev_id": OTHER_ROOT})

    assert not edit_locks.was_moved_elsewhere(root_id=ROOT)


def test_a_lock_holds_while_its_view_is_heard_from_and_lapses_after() -> None:
    clock = edit_locks_module.monotonic
    _mac_edits_the_child()
    clock.now += LEASE_SECONDS - 1
    edit_locks.heard_from(view_id=MAC, token=MAC_BROWSER, user_agent=DESKTOP_AGENT)
    clock.now += LEASE_SECONDS - 1
    assert edit_locks.locked_roots_for(view_id=PHONE) == {ROOT: ON_ANOTHER_COMPUTER}, "no idle timer"

    clock.now += 2
    assert edit_locks.locked_roots_for(view_id=PHONE) == {}
    with as_phone():
        _save(ROOT)


def test_ending_the_edit_or_switching_roots_lets_go() -> None:
    _mac_edits_the_child()
    edit_locks.sync_editing(view_id=MAC, note_id=OTHER_ROOT, tells_taken=True)
    assert edit_locks.locked_roots_for(view_id=PHONE) == {OTHER_ROOT: ON_ANOTHER_COMPUTER}

    edit_locks.sync_editing(view_id=MAC, note_id="", tells_taken=True)
    assert edit_locks.locked_roots_for(view_id=PHONE) == {}


def test_take_over_waits_for_the_editing_view_to_save_and_leave() -> None:
    _mac_edits_the_child()

    assert edit_locks.take_over(view_id=PHONE, note_id=ROOT, is_for_change=False) is False
    with as_mac():
        _save(CHILD)
    assert edit_locks.sync_editing(view_id=MAC, note_id=CHILD, tells_taken=True) == {
        "rootId": ROOT, "takenWhere": ON_YOUR_PHONE, "maySave": True, "isForChange": False,
    }
    assert edit_locks.take_over(view_id=PHONE, note_id=ROOT, is_for_change=False) is False, "the Mac is still saving"
    edit_locks.sync_editing(view_id=MAC, note_id="", tells_taken=True)

    assert edit_locks.take_over(view_id=PHONE, note_id=ROOT, is_for_change=False) is True
    assert edit_locks.locked_roots_for(view_id=MAC) == {ROOT: ON_YOUR_PHONE}
    with as_mac(), pytest.raises(NoteLockedElsewhere):
        _save(CHILD)


def test_a_take_over_for_a_change_says_so_to_the_editing_view() -> None:
    """A fold or a tick there, not editing: the Mac says editing ended, not that it moved."""
    _mac_edits_the_child()

    assert edit_locks.take_over(view_id=PHONE, note_id=ROOT, is_for_change=True) is False
    assert edit_locks.sync_editing(view_id=MAC, note_id=CHILD, tells_taken=True) == {
        "rootId": ROOT, "takenWhere": ON_YOUR_PHONE, "maySave": True, "isForChange": True,
    }


def test_take_over_goes_ahead_when_the_editing_view_does_not_answer() -> None:
    clock = edit_locks_module.monotonic
    _mac_edits_the_child()
    edit_locks.take_over(view_id=PHONE, note_id=ROOT, is_for_change=False)

    clock.now += HANDOVER_SECONDS
    assert edit_locks.take_over(view_id=PHONE, note_id=ROOT, is_for_change=False) is True
    with as_mac(), pytest.raises(NoteLockedElsewhere):
        _save(CHILD)


def test_signing_out_lets_go_of_that_browsers_roots_only() -> None:
    _mac_edits_the_child()
    edit_locks.sync_editing(view_id=PHONE, note_id=OTHER_ROOT, tells_taken=True)

    edit_locks.forget_browsers(tokens=[MAC_BROWSER])

    assert edit_locks.locked_roots_for(view_id=MAC_TAB_TWO) == {OTHER_ROOT: ON_YOUR_PHONE}


def test_background_work_and_storage_rewrites_are_not_checked() -> None:
    _mac_edits_the_child()

    _save(ROOT)
    with as_phone(), edit_locks.storage_rewrite():
        _save(ROOT)


def test_a_search_being_typed_is_locked_for_the_others_until_typing_pauses() -> None:
    clock = edit_locks_module.monotonic
    edit_locks.note_search_typed(view_id=MAC, tab_id=TAB)

    assert edit_locks.search_locks_for(view_id=PHONE) == {TAB: ON_ANOTHER_COMPUTER}
    with pytest.raises(SearchLockedElsewhere):
        edit_locks.note_search_typed(view_id=PHONE, tab_id=TAB)
    clock.now += SEARCH_LOCK_SECONDS
    edit_locks.note_search_typed(view_id=PHONE, tab_id=TAB)
    assert edit_locks.search_locks_for(view_id=MAC) == {TAB: ON_YOUR_PHONE}

    edit_locks.release_search(view_id=PHONE)
    assert edit_locks.search_locks_for(view_id=MAC) == {}


def test_a_question_typed_for_the_ai_is_locked_for_the_others_until_left() -> None:
    edit_locks.note_composer_typed(view_id=MAC, text="What did I")

    assert edit_locks.composer_for(view_id=PHONE) == {"where": ON_ANOTHER_COMPUTER, "text": "What did I"}
    assert edit_locks.composer_for(view_id=MAC) == {}
    with pytest.raises(ComposerLockedElsewhere):
        edit_locks.note_composer_typed(view_id=PHONE, text="Hello")
    edit_locks_module.monotonic.now += SEARCH_LOCK_SECONDS * 10
    edit_locks.heard_from(view_id=MAC, token=MAC_BROWSER, user_agent=DESKTOP_AGENT)
    assert edit_locks.composer_for(view_id=PHONE)["text"] == "What did I", "no idle timer while the box is used"

    edit_locks.release_composer(view_id=MAC)
    assert edit_locks.composer_for(view_id=PHONE) == {}
    edit_locks.note_composer_typed(view_id=PHONE, text="Hello")


def test_only_root_locks_move_the_revision_views_refresh_their_notes_for() -> None:
    """A view refreshes its notes when the edit-lock revision moves (its root markers). A search or
    an AI question being typed moves it no more: they reach the other views by their own
    revisions, and a view alone refreshed its whole list for its own search typing (found
    2026-11-15: every search in a 100,000-note vault queued behind such a refresh)."""
    before = edit_locks.revision()
    edit_locks.note_search_typed(view_id=MAC, tab_id=TAB)
    edit_locks.release_search(view_id=MAC)
    edit_locks.note_composer_typed(view_id=MAC, text="a question")
    edit_locks.release_composer(view_id=MAC)
    assert edit_locks.revision() == before

    _mac_edits_the_child()
    assert edit_locks.revision() > before
