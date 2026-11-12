"""A browser window's warm views go when sync forgets the idle client
(docs/ready-to-build/unbounded-growth-audit.md, M2)."""

import pytest

import app.services.sync as sync
from app.services.resource_limits import CLIENT_ENTRIES, CLIENT_IDLE_SECONDS
from app.services.view_cache import view_cache
from app.services.view_state import ViewState


def _state() -> ViewState:
    return ViewState(structure=[], payloads={}, locks={}, children_by_parent={None: ["n1"]}, hash_by_id={"n1": "h1"}, metadata={})


@pytest.fixture
def clock(monkeypatch):
    now = {"value": 1000.0}
    monkeypatch.setattr(sync, "monotonic", lambda: now["value"])
    sync.reset_state()
    view_cache.clear()
    yield now
    sync.reset_state()
    view_cache.clear()


def _open_view(client_id: str, tab_id: str) -> None:
    sync.touch_client(client_id)
    view_cache.set(client_id=client_id, tab_id=tab_id, state=_state())


def test_an_idle_client_loses_its_views_and_an_active_one_keeps_them(clock):
    _open_view("closed-window", "tab-1")
    _open_view("closed-window", "tab-2")
    _open_view("open-window", "tab-1")
    clock["value"] += CLIENT_IDLE_SECONDS - 1
    sync.touch_client("open-window")
    clock["value"] += 1

    sync.touch_client("open-window")

    assert view_cache.get(client_id="closed-window", tab_id="tab-1") is None
    assert view_cache.get(client_id="closed-window", tab_id="tab-2") is None
    assert view_cache.get(client_id="open-window", tab_id="tab-1") is not None


def test_a_client_dropped_for_the_client_cap_loses_its_views(clock):
    _open_view("oldest", "tab-1")
    for index in range(CLIENT_ENTRIES):
        clock["value"] += 1
        _open_view(f"client-{index}", "tab-1")

    assert view_cache.get(client_id="oldest", tab_id="tab-1") is None
    assert view_cache.get(client_id=f"client-{CLIENT_ENTRIES - 1}", tab_id="tab-1") is not None
