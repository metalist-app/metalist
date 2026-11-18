"""How the page saves its place in the tabs, for tests of the tab state (tab-state-service.js,
persistTabStateSnapshot): by name, its scroll in each tab and then each reference page it opened
or changed. The server takes no copy of a view's tabs."""

from __future__ import annotations

from typing import Dict

from app.services.tab_state import TabStateStore

_SCROLL_KEYS = ("scrollY", "anchorRootId", "scrollAnchor")


def save_as_the_page_does(
    store: TabStateStore,
    *,
    view_id: str,
    tabs: Dict[str, Dict[str, object]],
    reference_views: Dict[str, Dict[str, object]],
    read_at_version: int,
) -> Dict[str, object]:
    """The view's tabs once the server has answered: tabs carries the view's scroll in each tab,
    reference_views the pages it opened or changed (the page sends no page it only read)."""
    for tab_id, tab in tabs.items():
        scroll = {key: tab[key] for key in _SCROLL_KEYS}
        store.set_scroll(view_id=view_id, tab_id=tab_id, scroll=scroll, read_at_version=read_at_version)
    for tab_id, page in reference_views.items():
        store.set_reference_page(
            view_id=view_id, tab_id=tab_id, from_tab_id=page["fromTabId"],
            reference_query=page["referenceQuery"], view_kind=page["viewKind"],
            origin_scope=page["originScope"],
        )
    return store.snapshot(view_id=view_id)
