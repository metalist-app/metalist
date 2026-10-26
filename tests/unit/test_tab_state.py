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


def test_create_tab_copies_sort_mode_from_source_tab() -> None:
    store = TabStateStore()
    initial = store.snapshot()
    source_tab_id = initial["activeTabId"]
    updated = store.set_sort_mode(tab_id=source_tab_id, sort_mode="updated")

    duplicated = store.create_tab(copy_from_tab_id=source_tab_id)
    new_tab_id = duplicated["newTabId"]

    assert duplicated["tabs"][new_tab_id]["sortMode"] == "updated"
    assert updated["tabs"][source_tab_id]["sortMode"] == "updated"


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
