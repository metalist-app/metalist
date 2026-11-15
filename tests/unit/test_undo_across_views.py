"""Each view's undo history builds from its own edits; any change to the notes from another view
empties it (the maintainer, 2026-11-14; docs/design/multi-view-editing.md §10). Undo put
back a step's "before" state blindly, so after another device's change it would have overwritten
that change. Undo or Redo then changes nothing and says why."""

from __future__ import annotations

import pytest

from app.services import undo_state
from app.usecases.redo import CmdRedo
from app.usecases.undo import CmdUndo

CHANGED_ELSEWHERE = "Nothing to undo: notes were changed on another device."
REDO_CHANGED_ELSEWHERE = "Nothing to redo: notes were changed on another device."
CONTEXT = "context"
VIEWPORT = {"scrollY": 0, "scrollAnchor": None}


@pytest.fixture(autouse=True)
def _no_undo_history():
    undo_state.reset_all_undo_state()
    yield
    undo_state.reset_all_undo_state()


def _edit(client_id: str, note_id: str) -> None:
    undo_state.record_update(client_id, CONTEXT, note_id, before="before", after="after",
                             before_tags="", after_tags="", viewport=VIEWPORT)


def _undo(client_id: str) -> dict:
    return CmdUndo(client_id=client_id, token="token", undo_context=CONTEXT).execute()


def test_another_views_change_empties_this_views_undo_and_says_why() -> None:
    _edit("mac", "note-a")
    _edit("phone", "note-b")

    answer = _undo("mac")

    assert answer["status"] == "noop"
    assert answer["message"] == CHANGED_ELSEWHERE


def test_the_view_that_changed_keeps_its_own_undo() -> None:
    _edit("mac", "note-a")
    _edit("phone", "note-b")

    assert len(undo_state._ctx("phone").history) == 1


def test_a_views_own_edits_after_that_build_a_new_history() -> None:
    _edit("mac", "note-a")
    _edit("phone", "note-b")
    _edit("mac", "note-c")

    assert [op["note_id"] for op in undo_state._ctx("mac").history] == ["note-c"]
    assert _undo_message_when_empty("mac") == "No actions to undo", "said only until this view changes again"


def _undo_message_when_empty(client_id: str) -> str:
    undo_state._ctx(client_id).history.clear()
    return _undo(client_id)["message"]


def test_redo_is_emptied_too_and_says_why() -> None:
    _edit("mac", "note-a")
    ctx = undo_state._ctx("mac")
    ctx.redo.append(ctx.history.pop())
    _edit("phone", "note-b")

    answer = CmdRedo(client_id="mac", token="token", undo_context=CONTEXT).execute()

    assert answer["status"] == "noop"
    assert answer["message"] == REDO_CHANGED_ELSEWHERE
    assert answer["changedOnAnotherDevice"] is True


def test_a_view_with_nothing_to_undo_is_not_told_about_other_devices() -> None:
    _edit("phone", "note-b")

    assert _undo("mac")["message"] == "No actions to undo"
