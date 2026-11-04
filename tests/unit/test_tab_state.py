from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.db.session import begin_writer
from app.db.tab_state_sql import upsert_tab_state_row
from app.models.database import SafeSession
from app.security.encryption import set_encryption_required
from app.services.root_date_filter import make_root_date_filter
from app.services.tab_state import TabStateStore


@pytest.fixture(autouse=True)
def _isolated_memory_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    set_encryption_required(False)
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    try:
        yield
    finally:
        set_encryption_required(False)
        SafeSession.use_file_db()


def _bootstrapped_copy() -> TabStateStore:
    reloaded = TabStateStore()
    session = SafeSession()
    try:
        with SafeSession.allow_reads("tests:tab_state:bootstrap"):
            reloaded.bootstrap(connection=session.connection())
    finally:
        session.close()
    return reloaded


def _store_with_a_narrowed_tab() -> tuple[TabStateStore, str]:
    """A store whose tab searches, is sorted, has a date range, a Files filter and the Untagged view."""
    store = TabStateStore()
    snapshot = store.snapshot()
    tab_id = snapshot["activeTabId"]
    snapshot["tabs"][tab_id]["searchQuery"] = "journal"
    store.update(reference_views={}, active_tab_id=tab_id, tabs=snapshot["tabs"],
                 tab_order=snapshot["tabOrder"], read_at_version=snapshot["version"])
    store.set_sort_mode(tab_id=tab_id, sort_mode="created")
    store.set_date_filter(tab_id=tab_id, date_filter=make_root_date_filter(
        field="updated", range_kind="today", from_date="", to_date=""))
    store.set_file_filter(tab_id=tab_id, file_filter="pdf")
    store.set_untagged_view(tab_id=tab_id, is_untagged_view=True)
    return store, tab_id


# Duplicating a search context copies everything that decides which notes it shows and their
# order; a new one starts with nothing (the maintainer, 2026-11-02, docs/ui/state-handling.md).
def test_a_duplicate_copies_the_search_sort_date_range_files_filter_and_untagged_view() -> None:
    store, source_tab_id = _store_with_a_narrowed_tab()

    duplicated = store.create_tab(copy_from_tab_id=source_tab_id, copies_view=True)
    new_tab_id = duplicated["newTabId"]

    assert duplicated["tabs"][new_tab_id]["searchQuery"] == "journal"
    assert duplicated["tabs"][new_tab_id]["sortMode"] == "created"
    assert duplicated["dateFilters"][new_tab_id] == duplicated["dateFilters"][source_tab_id]
    assert duplicated["fileFilters"][new_tab_id] == "pdf"
    assert sorted(duplicated["untaggedViews"]) == sorted([source_tab_id, new_tab_id])


def test_a_new_tab_starts_with_nothing() -> None:
    store, source_tab_id = _store_with_a_narrowed_tab()

    created = store.create_tab(copy_from_tab_id=source_tab_id, copies_view=False)
    new_tab_id = created["newTabId"]

    assert created["tabs"][new_tab_id] == {
        "searchQuery": "", "scrollY": 0, "anchorRootId": None, "scrollAnchor": None, "sortMode": "normal",
    }
    assert new_tab_id not in created["dateFilters"]
    assert new_tab_id not in created["fileFilters"]
    assert created["untaggedViews"] == [source_tab_id]


def test_a_tab_keeps_its_untagged_view_across_a_reload_and_a_closed_tab_drops_it() -> None:
    store = TabStateStore()
    tab_id = store.snapshot()["activeTabId"]
    store.update(reference_views={}, active_tab_id=tab_id, tabs={tab_id: {**store.snapshot()["tabs"][tab_id], "scrollY": 120}},
                 tab_order=[tab_id], read_at_version=store.snapshot()["version"])

    result = store.set_untagged_view(tab_id=tab_id, is_untagged_view=True)
    assert result["changed"] is True
    assert result["untaggedViews"] == [tab_id]
    assert result["tabs"][tab_id]["scrollY"] == 0, "a view that shows other notes starts at its top"
    assert store.set_untagged_view(tab_id=tab_id, is_untagged_view=True)["changed"] is False

    assert _bootstrapped_copy().snapshot()["untaggedViews"] == [tab_id]

    new_tab_id = store.create_tab(copy_from_tab_id=tab_id, copies_view=True)["newTabId"]
    assert store.delete_tab(tab_id=new_tab_id)["untaggedViews"] == [tab_id]

    cleared = store.set_untagged_view(tab_id=tab_id, is_untagged_view=False)
    assert cleared["changed"] is True
    assert cleared["untaggedViews"] == []


def test_tab_state_saved_before_untagged_views_were_kept_has_none() -> None:
    store = TabStateStore()
    snapshot = store.snapshot()
    stored = json.dumps({key: snapshot[key] for key in ("activeTabId", "tabs", "tabOrder", "version")})
    assert store._deserialize_snapshot_json(stored)["untaggedViews"] == []


def test_set_sort_mode_resets_scroll_state_and_marks_change() -> None:
    store = TabStateStore()
    snapshot = store.snapshot()
    tab_id = snapshot["activeTabId"]
    payload = snapshot["tabs"]
    payload[tab_id]["scrollY"] = 250
    payload[tab_id]["scrollAnchor"] = {
        "anchorId": "root-a",
        "anchorBias": "top",
        "intraOffset": 0,
        "beltPrev": [],
        "beltNext": [],
        "anchorSortKey": {"domIndex": 0},
    }
    store.update(reference_views={}, 
        active_tab_id=tab_id,
        tabs=payload,
        tab_order=snapshot["tabOrder"],
        read_at_version=snapshot["version"],
    )

    result = store.set_sort_mode(tab_id=tab_id, sort_mode="created")

    assert result["changed"] is True
    assert result["tabs"][tab_id]["sortMode"] == "created"
    assert result["tabs"][tab_id]["scrollY"] == 0
    assert result["tabs"][tab_id]["scrollAnchor"] is None


def test_set_sort_mode_is_noop_when_value_matches() -> None:
    store = TabStateStore()
    snapshot = store.snapshot()
    tab_id = snapshot["activeTabId"]

    result = store.set_sort_mode(tab_id=tab_id, sort_mode="normal")

    assert result["changed"] is False
    assert result["tabs"][tab_id]["sortMode"] == "normal"


def test_set_sort_mode_accepts_alphabetical() -> None:
    store = TabStateStore()
    snapshot = store.snapshot()
    tab_id = snapshot["activeTabId"]

    result = store.set_sort_mode(tab_id=tab_id, sort_mode="alphabetical")

    assert result["changed"] is True
    assert result["tabs"][tab_id]["sortMode"] == "alphabetical"


def test_set_sort_mode_accepts_content_volume() -> None:
    store = TabStateStore()
    snapshot = store.snapshot()
    tab_id = snapshot["activeTabId"]

    result = store.set_sort_mode(tab_id=tab_id, sort_mode="content-volume")

    assert result["changed"] is True
    assert result["tabs"][tab_id]["sortMode"] == "content-volume"


def test_bootstrap_restores_persisted_tab_state() -> None:
    store = TabStateStore()
    initial = store.snapshot()
    tab_id = initial["activeTabId"]
    payload = initial["tabs"]
    payload[tab_id]["searchQuery"] = "project-x"
    payload[tab_id]["scrollY"] = 180
    payload[tab_id]["anchorRootId"] = "root-1"
    payload[tab_id]["scrollAnchor"] = {
        "anchorId": "root-1",
        "anchorBias": "top",
        "intraOffset": 12,
        "beltPrev": ["root-0"],
        "beltNext": ["root-2"],
        "anchorSortKey": {"domIndex": 3},
    }
    persisted = store.update(reference_views={}, 
        active_tab_id=tab_id,
        tabs=payload,
        tab_order=initial["tabOrder"],
        read_at_version=initial["version"],
    )

    reloaded = TabStateStore()
    session = SafeSession()
    try:
        with SafeSession.allow_reads("tests:tab_state:bootstrap"):
            reloaded.bootstrap(connection=session.connection())
    finally:
        session.close()

    snapshot = reloaded.snapshot()
    assert snapshot == persisted
    assert snapshot["tabs"][tab_id]["searchQuery"] == "project-x"
    assert snapshot["tabs"][tab_id]["anchorRootId"] == "root-1"


def test_legacy_tab_payload_discards_removed_calendar_state() -> None:
    store = TabStateStore()
    legacy_snapshot = store.snapshot()
    tab_id = legacy_snapshot["activeTabId"]
    payload = legacy_snapshot["tabs"]
    payload[tab_id]["dateFilter"] = {
        "metric": "created",
        "startDate": "2026-05-01",
        "endDate": "2026-05-18",
    }
    payload[tab_id]["calendarMetric"] = "updated"
    payload[tab_id]["calendarScrollTop"] = 333
    payload[tab_id]["calendarScrollPinnedToNewest"] = False

    with begin_writer() as connection:
        upsert_tab_state_row(
            connection,
            state_json=json.dumps(legacy_snapshot),
            state_encryption_nonce=None,
            state_encryption_tag=None,
            updated_at=datetime.now(timezone.utc),
        )

    reloaded = TabStateStore()
    session = SafeSession()
    try:
        with SafeSession.allow_reads("tests:tab_state:legacy_calendar_fields"):
            reloaded.bootstrap(connection=session.connection())
    finally:
        session.close()

    normalized_tab = reloaded.snapshot()["tabs"][tab_id]
    assert "dateFilter" not in normalized_tab
    assert "calendarMetric" not in normalized_tab
    assert "calendarScrollTop" not in normalized_tab
    assert "calendarScrollPinnedToNewest" not in normalized_tab


_OLD_VIEW_SCROLL = {
    "scrollY": 120,
    "anchorRootId": "root-1",
    "scrollAnchor": {
        "anchorId": "root-1", "anchorBias": "top", "intraOffset": 0,
        "beltPrev": [], "beltNext": [], "anchorSortKey": {"domIndex": 0},
    },
}
_RESTARTED_SCROLL = {"scrollY": 0, "anchorRootId": None, "scrollAnchor": None}


def _scroll_of(state: dict, tab_id: str) -> dict:
    return {key: state["tabs"][tab_id][key] for key in _RESTARTED_SCROLL}


def _restart_by_sort(store: TabStateStore, tab_id: str) -> None:
    store.set_sort_mode(tab_id=tab_id, sort_mode="alphabetical")


def _restart_by_date_range(store: TabStateStore, tab_id: str) -> None:
    store.set_date_filter(tab_id=tab_id, date_filter=make_root_date_filter(
        field="created", range_kind="custom", from_date="2026-10-01", to_date="2026-10-22",
    ))


@pytest.mark.parametrize("restart_view", [_restart_by_sort, _restart_by_date_range])
def test_snapshot_read_before_a_view_change_keeps_the_new_order_and_its_top(restart_view) -> None:
    # The browser's scroll or search save is read before it is sent, so one read
    # before a new sort order or date range can reach the server after it. Its sort
    # order and its place in the old view must not replace the new view's.
    store = TabStateStore()
    stale = store.snapshot()
    tab_id = stale["activeTabId"]
    stale["tabs"][tab_id].update(_OLD_VIEW_SCROLL)
    stale["tabs"][tab_id]["searchQuery"] = "typed before"
    restart_view(store, tab_id)
    sort_mode = store.get_sort_mode(tab_id=tab_id)

    saved = store.update(
        reference_views={}, active_tab_id=tab_id, tabs=stale["tabs"], tab_order=stale["tabOrder"],
        read_at_version=stale["version"],
    )

    assert saved["tabs"][tab_id]["sortMode"] == sort_mode
    assert _scroll_of(saved, tab_id) == _RESTARTED_SCROLL
    assert saved["tabs"][tab_id]["searchQuery"] == "typed before"

    # A save read after the change keeps the scroll it carries, and still the sort order.
    fresh = store.snapshot()
    fresh["tabs"][tab_id].update(_OLD_VIEW_SCROLL)
    fresh["tabs"][tab_id]["sortMode"] = "normal"
    moved = store.update(
        reference_views={}, active_tab_id=tab_id, tabs=fresh["tabs"], tab_order=fresh["tabOrder"],
        read_at_version=fresh["version"],
    )
    assert moved["tabs"][tab_id]["sortMode"] == sort_mode
    assert _scroll_of(moved, tab_id) == {key: _OLD_VIEW_SCROLL[key] for key in _RESTARTED_SCROLL}


def test_unchanged_update_keeps_version_and_skips_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    store = TabStateStore()
    snapshot = store.snapshot()
    tab_id = snapshot["activeTabId"]
    snapshot["tabs"][tab_id]["scrollY"] = 120
    changed = store.update(
        reference_views={}, active_tab_id=tab_id, tabs=snapshot["tabs"], tab_order=snapshot["tabOrder"],
        read_at_version=snapshot["version"],
    )
    writes: list[bool] = []
    monkeypatch.setattr(store, "_persist_locked", lambda **_kwargs: writes.append(True))

    unchanged = store.update(
        reference_views={}, active_tab_id=tab_id, tabs=changed["tabs"], tab_order=changed["tabOrder"],
        read_at_version=changed["version"],
    )

    assert unchanged["version"] == changed["version"]
    assert writes == []
    changed["tabs"][tab_id]["scrollY"] = 240
    moved = store.update(
        reference_views={}, active_tab_id=tab_id, tabs=changed["tabs"], tab_order=changed["tabOrder"],
        read_at_version=changed["version"],
    )
    assert moved["version"] == changed["version"] + 1
    assert writes == [True]
