"""How the page saves its place in the tabs, for tests of the tab state (tab-state-service.js,
persistTabStateSnapshot): its scroll in each tab by name, then its copy of the tabs."""

from __future__ import annotations

from typing import Dict, List

from app.services.tab_state import TabStateStore

_SCROLL_KEYS = ("scrollY", "anchorRootId", "scrollAnchor")


def save_as_the_page_does(
    store: TabStateStore,
    *,
    view_id: str,
    tabs: Dict[str, Dict[str, object]],
    tab_order: List[str],
    reference_views: object,
    read_at_version: int,
) -> Dict[str, object]:
    """The answer to the copy, which comes last and carries everything taken before it."""
    for tab_id, tab in tabs.items():
        scroll = {key: tab[key] for key in _SCROLL_KEYS}
        store.set_scroll(view_id=view_id, tab_id=tab_id, scroll=scroll, read_at_version=read_at_version)
    return store.update(
        view_id=view_id, tabs=tabs, tab_order=tab_order, reference_views=reference_views,
        read_at_version=read_at_version,
    )
