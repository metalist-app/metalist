from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.db.session import begin_writer
from app.db.tab_state_sql import upsert_tab_state_row
from app.models.database import SafeSession
from app.security.encryption import set_encryption_required
from app.services.input_errors import InputRejected
from app.services.root_date_filter import make_root_date_filter
from app.services.tab_state import TabStateStore
from tests.unit.tab_copy_saving import save_as_the_page_does

# The view (a browser tab) the tests act in (multi-view editing step 2).
VIEW = "10000000-0000-4000-8000-0000000000ee"


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
    snapshot = store.snapshot(view_id=VIEW)
    tab_id = snapshot["activeTabId"]
    store.set_search(view_id=VIEW, tab_id=tab_id, search_query="journal")
    store.set_sort_mode(view_id=VIEW, tab_id=tab_id, sort_mode="created")
    store.set_date_filter(view_id=VIEW, tab_id=tab_id, date_filter=make_root_date_filter(
        field="updated", range_kind="today", from_date="", to_date=""))
    store.set_file_filter(view_id=VIEW, tab_id=tab_id, file_filter="pdf")
    store.set_untagged_view(view_id=VIEW, tab_id=tab_id, is_untagged_view=True)
    return store, tab_id


# Duplicating a search context copies everything that decides which notes it shows and their
# order; a new one starts with nothing (the maintainer, 2026-11-02, docs/ui/state-handling.md).
def test_a_duplicate_copies_the_search_sort_date_range_files_filter_and_untagged_view() -> None:
    store, source_tab_id = _store_with_a_narrowed_tab()

    duplicated = store.create_tab(view_id=VIEW, is_page=False, copy_from_tab_id=source_tab_id, copies_view=True)
    new_tab_id = duplicated["newTabId"]

    assert duplicated["tabs"][new_tab_id]["searchQuery"] == "journal"
    assert duplicated["tabs"][new_tab_id]["sortMode"] == "created"
    assert duplicated["dateFilters"][new_tab_id] == duplicated["dateFilters"][source_tab_id]
    assert duplicated["fileFilters"][new_tab_id] == "pdf"
    assert sorted(duplicated["untaggedViews"]) == sorted([source_tab_id, new_tab_id])


def test_a_new_tab_starts_with_nothing() -> None:
    store, source_tab_id = _store_with_a_narrowed_tab()

    created = store.create_tab(view_id=VIEW, is_page=False, copy_from_tab_id=source_tab_id, copies_view=False)
    new_tab_id = created["newTabId"]

    assert created["tabs"][new_tab_id] == {
        "searchQuery": "", "scrollY": 0, "anchorRootId": None, "scrollAnchor": None, "sortMode": "normal",
    }
    assert new_tab_id not in created["dateFilters"]
    assert new_tab_id not in created["fileFilters"]
    assert created["untaggedViews"] == [source_tab_id]


def test_a_save_read_before_this_view_made_a_tab_keeps_that_tab() -> None:
    # Found 2026-11-15: a view saved its tabs (taking a change made in another view) while it was
    # making a new tab; the save, read before the new tab, could not name it and was refused.
    store = TabStateStore()
    before = store.snapshot(view_id=VIEW)
    tab_id = before["activeTabId"]
    created = store.create_tab(view_id=VIEW, is_page=False, copy_from_tab_id=tab_id, copies_view=False)
    new_tab_id = created["newTabId"]

    saved = save_as_the_page_does(store, view_id=VIEW, reference_views={}, tabs=before["tabs"],
                         tab_order=before["tabOrder"], read_at_version=before["version"])

    assert new_tab_id in saved["tabs"]
    assert saved["tabOrder"] == [tab_id, new_tab_id]


def test_a_save_that_leaves_out_a_tab_keeps_it_whatever_version_it_names() -> None:
    # The tabs are the server's: a copy takes none away (delete_tab does). Refused until
    # 2026-11-17, when a view whose version an answer to its own change had raised saved a copy
    # read before another view made a context (the live-changes suite).
    store = TabStateStore()
    first = store.snapshot(view_id=VIEW)
    tab_id = first["activeTabId"]
    created = store.create_tab(view_id=VIEW, is_page=False, copy_from_tab_id=tab_id, copies_view=False)

    saved = save_as_the_page_does(store, view_id=VIEW, reference_views={}, tabs=first["tabs"],
                         tab_order=first["tabOrder"], read_at_version=created["version"])

    assert saved["tabOrder"] == [tab_id, created["newTabId"]]


def test_a_save_naming_a_tab_the_server_never_had_is_refused() -> None:
    store = TabStateStore()
    first = store.snapshot(view_id=VIEW)
    tab_id = first["activeTabId"]
    unknown = "30000000-0000-4000-8000-0000000000c1"

    with pytest.raises(InputRejected, match="tab ids mismatch"):
        store.update(view_id=VIEW, reference_views={}, tabs={**first["tabs"], unknown: dict(first["tabs"][tab_id])},
                     tab_order=[tab_id, unknown], read_at_version=first["version"])


def test_a_tab_keeps_its_untagged_view_across_a_reload_and_a_closed_tab_drops_it() -> None:
    store = TabStateStore()
    tab_id = store.snapshot(view_id=VIEW)["activeTabId"]
    save_as_the_page_does(store, view_id=VIEW, reference_views={}, tabs={tab_id: {**store.snapshot(view_id=VIEW)["tabs"][tab_id], "scrollY": 120}},
                 tab_order=[tab_id], read_at_version=store.snapshot(view_id=VIEW)["version"])

    result = store.set_untagged_view(view_id=VIEW, tab_id=tab_id, is_untagged_view=True)
    assert result["changed"] is True
    assert result["untaggedViews"] == [tab_id]
    assert result["tabs"][tab_id]["scrollY"] == 0, "a view that shows other notes starts at its top"
    assert store.set_untagged_view(view_id=VIEW, tab_id=tab_id, is_untagged_view=True)["changed"] is False

    assert _bootstrapped_copy().snapshot(view_id=VIEW)["untaggedViews"] == [tab_id]

    new_tab_id = store.create_tab(view_id=VIEW, is_page=False, copy_from_tab_id=tab_id, copies_view=True)["newTabId"]
    assert store.delete_tab(view_id=VIEW, tab_id=new_tab_id)["untaggedViews"] == [tab_id]

    cleared = store.set_untagged_view(view_id=VIEW, tab_id=tab_id, is_untagged_view=False)
    assert cleared["changed"] is True
    assert cleared["untaggedViews"] == []


def test_tab_state_saved_before_untagged_views_were_kept_has_none() -> None:
    store = TabStateStore()
    snapshot = store.snapshot(view_id=VIEW)
    stored = json.dumps({key: snapshot[key] for key in ("activeTabId", "tabs", "tabOrder", "version")})
    assert store._deserialize_snapshot_json(stored)["untaggedViews"] == []


def test_set_sort_mode_resets_scroll_state_and_marks_change() -> None:
    store = TabStateStore()
    snapshot = store.snapshot(view_id=VIEW)
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
    save_as_the_page_does(store, view_id=VIEW, reference_views={}, 
        tabs=payload,
        tab_order=snapshot["tabOrder"],
        read_at_version=snapshot["version"],
    )

    result = store.set_sort_mode(view_id=VIEW, tab_id=tab_id, sort_mode="created")

    assert result["changed"] is True
    assert result["tabs"][tab_id]["sortMode"] == "created"
    assert result["tabs"][tab_id]["scrollY"] == 0
    assert result["tabs"][tab_id]["scrollAnchor"] is None


def test_set_sort_mode_is_noop_when_value_matches() -> None:
    store = TabStateStore()
    snapshot = store.snapshot(view_id=VIEW)
    tab_id = snapshot["activeTabId"]

    result = store.set_sort_mode(view_id=VIEW, tab_id=tab_id, sort_mode="normal")

    assert result["changed"] is False
    assert result["tabs"][tab_id]["sortMode"] == "normal"


def test_set_sort_mode_accepts_alphabetical() -> None:
    store = TabStateStore()
    snapshot = store.snapshot(view_id=VIEW)
    tab_id = snapshot["activeTabId"]

    result = store.set_sort_mode(view_id=VIEW, tab_id=tab_id, sort_mode="alphabetical")

    assert result["changed"] is True
    assert result["tabs"][tab_id]["sortMode"] == "alphabetical"


def test_set_sort_mode_accepts_content_volume() -> None:
    store = TabStateStore()
    snapshot = store.snapshot(view_id=VIEW)
    tab_id = snapshot["activeTabId"]

    result = store.set_sort_mode(view_id=VIEW, tab_id=tab_id, sort_mode="content-volume")

    assert result["changed"] is True
    assert result["tabs"][tab_id]["sortMode"] == "content-volume"


def test_bootstrap_restores_persisted_tab_state() -> None:
    store = TabStateStore()
    initial = store.snapshot(view_id=VIEW)
    tab_id = initial["activeTabId"]
    initial = store.set_search(view_id=VIEW, tab_id=tab_id, search_query="project-x")
    payload = initial["tabs"]
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
    persisted = save_as_the_page_does(store, view_id=VIEW, reference_views={}, 
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

    snapshot = reloaded.snapshot(view_id=VIEW)
    # The shared contexts' revision counts changes this server saw, not what is saved.
    del snapshot["searchContextsRevision"], persisted["searchContextsRevision"]
    assert snapshot == persisted
    assert snapshot["tabs"][tab_id]["searchQuery"] == "project-x"
    assert snapshot["tabs"][tab_id]["anchorRootId"] == "root-1"


def test_legacy_tab_payload_discards_removed_calendar_state() -> None:
    store = TabStateStore()
    legacy_snapshot = store.snapshot(view_id=VIEW)
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

    normalized_tab = reloaded.snapshot(view_id=VIEW)["tabs"][tab_id]
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
    store.set_sort_mode(view_id=VIEW, tab_id=tab_id, sort_mode="alphabetical")


def _restart_by_date_range(store: TabStateStore, tab_id: str) -> None:
    store.set_date_filter(view_id=VIEW, tab_id=tab_id, date_filter=make_root_date_filter(
        field="created", range_kind="custom", from_date="2026-10-01", to_date="2026-10-22",
    ))


@pytest.mark.parametrize("restart_view", [_restart_by_sort, _restart_by_date_range])
def test_snapshot_read_before_a_view_change_keeps_the_new_order_and_its_top(restart_view) -> None:
    # The browser's scroll save is read before it is sent, so one read before a new sort
    # order or date range can reach the server after it. Its sort order and its place in
    # the old view must not replace the new view's; the search, asked for by name, stays.
    store = TabStateStore()
    tab_id = store.snapshot(view_id=VIEW)["activeTabId"]
    stale = store.set_search(view_id=VIEW, tab_id=tab_id, search_query="typed before")
    stale["tabs"][tab_id].update(_OLD_VIEW_SCROLL)
    restart_view(store, tab_id)
    sort_mode = store.get_sort_mode(tab_id=tab_id)

    saved = save_as_the_page_does(store, view_id=VIEW, 
        reference_views={}, tabs=stale["tabs"], tab_order=stale["tabOrder"],
        read_at_version=stale["version"],
    )

    assert saved["tabs"][tab_id]["sortMode"] == sort_mode
    assert _scroll_of(saved, tab_id) == _RESTARTED_SCROLL
    assert saved["tabs"][tab_id]["searchQuery"] == "typed before"

    # A save read after the change keeps the scroll it carries, and still the sort order.
    fresh = store.snapshot(view_id=VIEW)
    fresh["tabs"][tab_id].update(_OLD_VIEW_SCROLL)
    fresh["tabs"][tab_id]["sortMode"] = "normal"
    moved = save_as_the_page_does(store, view_id=VIEW, 
        reference_views={}, tabs=fresh["tabs"], tab_order=fresh["tabOrder"],
        read_at_version=fresh["version"],
    )
    assert moved["tabs"][tab_id]["sortMode"] == sort_mode
    assert _scroll_of(moved, tab_id) == {key: _OLD_VIEW_SCROLL[key] for key in _RESTARTED_SCROLL}


def test_unchanged_update_keeps_version_and_skips_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    store = TabStateStore()
    snapshot = store.snapshot(view_id=VIEW)
    tab_id = snapshot["activeTabId"]
    snapshot["tabs"][tab_id]["scrollY"] = 120
    changed = save_as_the_page_does(store, view_id=VIEW, 
        reference_views={}, tabs=snapshot["tabs"], tab_order=snapshot["tabOrder"],
        read_at_version=snapshot["version"],
    )
    writes: list[bool] = []
    monkeypatch.setattr(store, "_persist_locked", lambda **_kwargs: writes.append(True))

    unchanged = save_as_the_page_does(store, view_id=VIEW, 
        reference_views={}, tabs=changed["tabs"], tab_order=changed["tabOrder"],
        read_at_version=changed["version"],
    )

    assert unchanged["version"] == changed["version"]
    assert writes == []
    changed["tabs"][tab_id]["scrollY"] = 240
    moved = save_as_the_page_does(store, view_id=VIEW, 
        reference_views={}, tabs=changed["tabs"], tab_order=changed["tabOrder"],
        read_at_version=changed["version"],
    )
    assert moved["version"] == changed["version"] + 1
    assert writes == [True]


# A folder clicked in the tree is a folder (it becomes the search: test_folders_tab.py).
def test_a_folder_clicked_must_be_a_folder() -> None:
    store = TabStateStore()
    tab_id = store.snapshot(view_id=VIEW)["activeTabId"]
    with pytest.raises(InputRejected, match="not a folder"):
        store.choose_folder(view_id=VIEW, tab_id=tab_id, folder="journal", adds=False)


def test_tab_state_saved_before_folders_were_kept_has_none() -> None:
    store = TabStateStore()
    snapshot = store.snapshot(view_id=VIEW)
    stored = json.dumps({key: snapshot[key] for key in ("activeTabId", "tabs", "tabOrder", "version")})
    assert store._deserialize_snapshot_json(stored)["folderFilters"] == {}
    assert store._deserialize_snapshot_json(stored)["treeShown"] is False
