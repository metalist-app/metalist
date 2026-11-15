"""A change refused because another view edits the root (multi-view editing step 4) is answered at
once: the request changed nothing, so nothing is reloaded. Found 2026-11-15 (the maintainer's problem
report): a refused collapse took 7.8 s, and both tabs waited behind it, because every failed
request that had opened a writer reloaded the whole vault from disk."""

from __future__ import annotations

import pytest

from app.api.transactions import transactional_route
from app.services import request_recovery
from app.services.edit_locks import NoteLockedElsewhere, edit_locks
from app.usecases.collapse import apply_set_collapse
from app.usecases.create_note import apply_insert_note
from app.usecases.update_content import apply_update_content
from tests.unit.test_phase_one_integrity import live_database  # noqa: F401  (the fixture)

MAC = "view-mac"
PHONE = "view-phone"


@pytest.fixture
def phone_edits_the_root(live_database):  # noqa: F811  (the fixture above)
    edit_locks.reset()
    apply_insert_note("locked-root", None, None, None, "", content="the root", tags="", proposed_tags="")
    apply_insert_note("other-root", None, "locked-root", None, "", content="another", tags="", proposed_tags="")
    edit_locks.heard_from(view_id=PHONE, token="phone-sign-in", user_agent="iPhone")
    assert edit_locks.sync_editing(view_id=PHONE, note_id="locked-root", tells_taken=True) == {}
    yield
    edit_locks.reset()


@pytest.fixture
def reloads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    monkeypatch.setattr(request_recovery, "reload_runtime_from_database", lambda **kwargs: seen.append("reload"))
    return seen


def _as_mac():
    return edit_locks.enter_request(view_id=MAC, token="mac-sign-in", user_agent="Macintosh")


def test_a_change_refused_before_any_write_reloads_nothing(phone_edits_the_root, reloads) -> None:
    @transactional_route
    def collapse_the_locked_root():
        apply_set_collapse("locked-root", True)

    entered = _as_mac()
    try:
        with pytest.raises(NoteLockedElsewhere):
            collapse_the_locked_root()
    finally:
        edit_locks.leave_request(entered)

    assert reloads == []


def test_a_change_refused_after_another_write_still_reloads(phone_edits_the_root, reloads) -> None:
    @transactional_route
    def change_another_then_the_locked_root():
        apply_update_content("other-root", "changed", "", "")
        apply_set_collapse("locked-root", True)

    entered = _as_mac()
    try:
        with pytest.raises(NoteLockedElsewhere):
            change_another_then_the_locked_root()
    finally:
        edit_locks.leave_request(entered)

    assert reloads == ["reload"]
