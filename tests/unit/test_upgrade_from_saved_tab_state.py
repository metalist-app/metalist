"""Tab state as MetaList 0.29.0 saved it loads, and works, on this version: customers upgrade from
such state (the maintainer, 2026-11-14). The fixture was made in a throwaway 0.29.0 the way its
reference views were used (tests/unit/saved_reference_views_harness.mjs says how); the browser's
side of the same state is tested by upgrade_from_saved_reference_views*.test.mjs."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.db.session import begin_writer
from app.db.tab_state_sql import upsert_tab_state_row
from app.models.database import SafeSession
from app.security.encryption import set_encryption_required
from app.services.tab_state import TabStateStore

FIXTURE = Path(__file__).parent.parent / "fixtures" / "upgrade" / "tab-state-v0.29.0.json"
CONTEXT = "ef7b4ecf-00a2-4938-91a8-0b25ae8d5f47"
TRIP_BACKLINKS = "baf9f2e7-3494-4036-901e-2b7d85c6eb2e"
CSV_SOURCE = "bc7dcdd5-7d2f-4fa1-863f-0205b3e949e6"
CSV_BACKLINKS = "b7107d8e-9f0b-4945-8d4a-608c21371acf"
LEFT_OPEN = "a35fe734-4758-4f87-80d1-99414032c6bc"
# The notes the pages show: the one linking Trip plan and embedding the CSV, and the CSV.
LINKING_NOTE = "46678338-6fba-401c-96fa-9f376ca25c7a"
CSV_NOTE = "015e1bec-ceea-490c-83df-cf9375f19794"


@pytest.fixture(autouse=True)
def _isolated_memory_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    set_encryption_required(False)
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    try:
        yield
    finally:
        set_encryption_required(False)
        SafeSession.use_file_db()


def _saved() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _loaded(saved: dict) -> TabStateStore:
    """A store started on `saved`, as the server starts on the vault's saved tabs."""
    with begin_writer() as connection:
        upsert_tab_state_row(
            connection, state_json=json.dumps(saved), state_encryption_nonce=None,
            state_encryption_tag=None, updated_at=datetime.now(timezone.utc),
        )
    store = TabStateStore()
    session = SafeSession()
    try:
        with SafeSession.allow_reads("tests:upgrade_from_saved_tab_state"):
            store.bootstrap(connection=session.connection())
    finally:
        session.close()
    return store


def test_tabs_saved_by_0_29_0_load_as_they_were() -> None:
    saved = _saved()
    state = _loaded(saved).snapshot()

    assert state["activeTabId"] == LEFT_OPEN
    assert state["tabOrder"] == saved["tabOrder"]
    assert state["referenceViews"] == saved["referenceViews"]
    assert {tab_id: tab["searchQuery"] for tab_id, tab in state["tabs"].items()} == {
        tab_id: tab["searchQuery"] for tab_id, tab in saved["tabs"].items()
    }


def test_the_browser_saves_them_back_as_this_version_keeps_pages() -> None:
    # The browser adopts the page left open under the page beside it, in the same search context
    # (upgrade_from_saved_reference_views.test.mjs), and saves that.
    store = _loaded(_saved())
    state = store.snapshot()
    views = copy.deepcopy(state["referenceViews"])
    views[LEFT_OPEN] = {
        "fromTabId": CSV_BACKLINKS, "referenceQuery": CSV_NOTE, "viewKind": "source",
        "originScope": copy.deepcopy(views[CSV_BACKLINKS]["originScope"]),
    }
    store.update(active_tab_id=LEFT_OPEN, tabs=state["tabs"], tab_order=state["tabOrder"],
                 reference_views=views, read_at_version=state["version"])

    assert store.snapshot()["referenceViews"] == views


def test_a_search_link_opens_beside_the_context_on_a_page() -> None:
    saved = _saved()
    # The context searched for something a search link can name (an empty search is none).
    saved["tabs"][CONTEXT]["searchQuery"] = "trip"
    store = _loaded(saved)

    # "": no context takes it, so the browser opens the search in a new one; the context on its
    # pages stays there.
    assert store.search_context_with_search(search="trip") == ""


def test_deleting_a_note_closes_the_saved_pages_showing_it() -> None:
    store = _loaded(_saved())

    assert store.close_pages_whose_notes_are_gone(note_exists=lambda note_id: note_id != LINKING_NOTE)

    state = store.snapshot()
    # Both Referenced by pages show the deleted note; the Source note opened from one goes with it.
    assert state["tabOrder"] == [CONTEXT, LEFT_OPEN]
    assert state["referenceViews"] == {}
    assert state["activeTabId"] == LEFT_OPEN


def test_a_saved_view_whose_search_context_0_29_0_closed_is_left_to_the_browser() -> None:
    # 0.29.0 left the views open when their search context closed; only one opened from another
    # view kept a record, still naming the closed context.
    saved = _saved()
    del saved["tabs"][CONTEXT]
    saved["tabOrder"].remove(CONTEXT)
    saved["referenceViews"] = {CSV_SOURCE: saved["referenceViews"][CSV_SOURCE]}
    saved["activeTabId"] = CSV_SOURCE

    store = _loaded(saved)

    state = store.snapshot()
    assert state["referenceViews"] == {}, "the browser gives it to a search context that is there"
    assert state["tabOrder"] == saved["tabOrder"]
    assert store.close_pages_whose_notes_are_gone(note_exists=lambda note_id: False) is False
