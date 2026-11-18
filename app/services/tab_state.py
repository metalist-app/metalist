from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import re
from threading import Lock
from time import time
from typing import Callable, Dict, List, Optional, Set
from uuid import uuid4

from app.db.session import begin_writer
from app.db.tab_state_sql import delete_tab_state_row, fetch_tab_state_row, upsert_tab_state_row
from app.security.encryption import (
    get_encryption_service,
    get_encryption_service_with_token,
    is_encryption_required,
)
from app.services.root_sorting import SORT_MODE_FILE_SIZE, SORT_MODE_NORMAL, SORT_MODES, base_sort_mode, normalize_sort_mode
from app.services.input_errors import InputRejected
from app.services.edit_locks import edit_locks
from app.services.search_links import same_search
from app.services.file_kinds import make_file_filter
from app.services.virtual_folders import NO_FOLDER, is_folder_tag, toggle_folder_in_search
from app.services.root_date_filter import RootDateFilter, root_date_filter_from_payload, root_date_filter_payload


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}$"
)
# The browser enforces the same limit (CONFIG.TABS.MAX_TABS in config.js).
_MAX_TABS = 1000
# Tab ids are UUIDs (36 characters); a request may carry at most this many, everywhere.
MAX_TAB_ID_LENGTH = 128


def _normalize_tab_sort_mode(sort_mode: object, *, from_storage: bool) -> str:
    """A saved sort mode this version does not know opens in normal order.

    Saved tab state can hold values from a removed feature (the similar-notes
    view saved "similarity:<note id>", docs/design/similar-notes-learnings.md)
    or from another version; only the known modes are kept. A request from the
    browser with an unknown sort mode is still a bug and fails.
    """
    if from_storage and not (isinstance(sort_mode, str) and sort_mode.strip().lower() in SORT_MODES):
        return SORT_MODE_NORMAL
    return normalize_sort_mode(sort_mode)


# Reference views (docs/ui/references.md): a tab that shows a note's source, the
# notes referencing it, or an AI answer's references, opened from another tab.
# They are kept with the tabs, so every window and reload labels them.
REFERENCE_VIEW_KINDS = frozenset({"source", "backlinks", "reference", "references"})
_REFERENCE_VIEW_KEYS = ("fromTabId", "referenceQuery", "viewKind", "originScope")
_ORIGIN_SCOPE_KEYS = ("scopeTabId", "searchQuery", "sortMode", "isUntaggedView")
# Where a tab is in its view. A new order or filter starts it again at the top.
_TAB_SCROLL_KEYS = ("scrollY", "scrollAnchor", "anchorRootId")


def _normalize_origin_scope(origin_scope: object, *, from_storage: bool) -> Dict[str, object]:
    if not isinstance(origin_scope, dict):
        raise InputRejected("referenceViews originScope must be an object")
    for key in _ORIGIN_SCOPE_KEYS:
        if key not in origin_scope:
            raise InputRejected(f"referenceViews originScope missing {key}")
    scope_tab_id = origin_scope["scopeTabId"]
    search_query = origin_scope["searchQuery"]
    is_untagged_view = origin_scope["isUntaggedView"]
    if not isinstance(scope_tab_id, str) or not _is_uuid_string(scope_tab_id):
        raise InputRejected("referenceViews originScope.scopeTabId must be a tab id")
    if not isinstance(search_query, str):
        raise InputRejected("referenceViews originScope.searchQuery must be a string")
    if not isinstance(is_untagged_view, bool):
        raise InputRejected("referenceViews originScope.isUntaggedView must be a boolean")
    return {
        "scopeTabId": scope_tab_id,
        "searchQuery": search_query,
        "sortMode": _normalize_tab_sort_mode(origin_scope["sortMode"], from_storage=from_storage),
        "isUntaggedView": is_untagged_view,
    }


# A note id in a reference view's search (one, or several joined by OR).
_NOTE_ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def _reference_note_ids(view: Dict[str, object]) -> List[str]:
    reference_query = view["referenceQuery"]
    assert isinstance(reference_query, str), "a reference view runs a search"
    return [note_id.lower() for note_id in _NOTE_ID_RE.findall(reference_query)]


def _origin_tab_id(view: Dict[str, object]) -> str:
    """The search context a reference view was opened from."""
    origin_scope = view["originScope"]
    assert isinstance(origin_scope, dict), "a reference view keeps its origin scope"
    scope_tab_id = origin_scope["scopeTabId"]
    assert isinstance(scope_tab_id, str), "an origin scope names its tab"
    return scope_tab_id


def _normalize_reference_views(
    views: object,
    tabs: Dict[str, Dict[str, object]],
    *,
    from_storage: bool,
) -> Dict[str, Dict[str, object]]:
    """Reference views by the tab showing them. A view has ended, and is dropped,
    when its tab, the tab it was opened from or its search context is gone, or its tab now
    runs another search; a saved view of a kind this version does not know is dropped too."""
    if not isinstance(views, dict):
        raise InputRejected("referenceViews must be an object")
    normalized: Dict[str, Dict[str, object]] = {}
    for tab_id, view in views.items():
        if not isinstance(tab_id, str) or not _is_uuid_string(tab_id):
            raise InputRejected("referenceViews keys must be tab ids")
        if not isinstance(view, dict):
            raise InputRejected("referenceViews entries must be objects")
        for key in _REFERENCE_VIEW_KEYS:
            if key not in view:
                raise InputRejected(f"referenceViews entry missing {key}")
        from_tab_id = view["fromTabId"]
        reference_query = view["referenceQuery"]
        view_kind = view["viewKind"]
        if not isinstance(from_tab_id, str) or not _is_uuid_string(from_tab_id):
            raise InputRejected("referenceViews fromTabId must be a tab id")
        if not isinstance(reference_query, str) or reference_query == "":
            raise InputRejected("referenceViews referenceQuery must be a non-empty string")
        if view_kind not in REFERENCE_VIEW_KINDS:
            if from_storage:
                continue
            raise InputRejected("referenceViews viewKind is not a known kind of view")
        origin_scope = _normalize_origin_scope(view["originScope"], from_storage=from_storage)
        if tab_id not in tabs or from_tab_id not in tabs or from_tab_id == tab_id:
            continue
        # 0.29.0 left a view open when the search context it came from was closed: it is a tab of
        # note IDs no view claims, which the browser gives back to a search context that is there.
        if origin_scope["scopeTabId"] not in tabs:
            continue
        if tabs[tab_id]["searchQuery"] != reference_query:
            continue
        normalized[tab_id] = {
            "fromTabId": from_tab_id,
            "referenceQuery": reference_query,
            "viewKind": view_kind,
            "originScope": origin_scope,
        }
    return normalized


def _normalize_date_filters(
    filters: object,
    tabs: Dict[str, Dict[str, object]],
) -> Dict[str, Dict[str, str]]:
    """Date range filters by tab (root_date_filter.py); a tab that is gone has none."""
    if not isinstance(filters, dict):
        raise InputRejected("dateFilters must be an object")
    normalized: Dict[str, Dict[str, str]] = {}
    for tab_id, payload in filters.items():
        if tab_id not in tabs:
            continue
        normalized[tab_id] = root_date_filter_payload(root_date_filter_from_payload(payload))
    return normalized


def _normalize_file_filters(filters: object, tabs: Dict[str, Dict[str, object]]) -> Dict[str, str]:
    """Files filters by tab (file_kinds.py); a tab that is gone has none."""
    if not isinstance(filters, dict):
        raise InputRejected("fileFilters must be an object")
    return {tab_id: make_file_filter(kind) for tab_id, kind in filters.items() if tab_id in tabs}


def _normalize_folder_filters(filters: object, tabs: Dict[str, Dict[str, object]]) -> Dict[str, str]:
    """The folders tabs were narrowed to before the folder became search text (2026-11-11,
    folder-tags-in-search.md §2), kept only to be converted once; a tab that is gone has none."""
    if not isinstance(filters, dict):
        raise InputRejected("folderFilters must be an object")
    for folder in filters.values():
        if not isinstance(folder, str) or not is_folder_tag(folder):
            raise RuntimeError(f"Stored folder filter is not a folder: {folder!r}")
    return {tab_id: folder for tab_id, folder in filters.items() if tab_id in tabs}


# The one folder context saved by the build tried on 2026-11-07, before there could be several:
# its tab, and the tab it was opened from (no longer kept).
_SINGLE_FOLDER_CONTEXT_KEYS = ("tabId", "originTabId")


def _stored_folder_contexts(parsed: Dict[str, object]) -> object:
    """The folder contexts as saved: a list of tabs; the one of the build tried on 2026-11-07
    (folderContext); none before that."""
    if "folderContexts" in parsed:
        return parsed["folderContexts"]
    if "folderContext" not in parsed:
        return []
    single = parsed["folderContext"]
    if not isinstance(single, dict):
        raise RuntimeError("Stored folderContext must be an object")
    if len(single) == 0:
        return []
    if set(single.keys()) != set(_SINGLE_FOLDER_CONTEXT_KEYS):
        raise RuntimeError(f"Stored folderContext must have exactly {_SINGLE_FOLDER_CONTEXT_KEYS}")
    return [single["tabId"]]


def _normalize_folder_contexts(tab_ids: object, tabs: Dict[str, Dict[str, object]]) -> Set[str]:
    """The tabs that were folder contexts (before 2026-11-11), kept only to convert them once
    (folders-tab-and-multiple-folders.md §1); a tab that is gone is none."""
    if not isinstance(tab_ids, list) or not all(isinstance(tab_id, str) for tab_id in tab_ids):
        raise RuntimeError("Stored folderContexts must be a list of tab ids")
    return {tab_id for tab_id in tab_ids if tab_id in tabs}


def _normalize_untagged_views(tab_ids: object, tabs: Dict[str, Dict[str, object]]) -> Set[str]:
    """The tabs showing the Untagged view; a tab that is gone shows none."""
    if not isinstance(tab_ids, list) or not all(isinstance(tab_id, str) for tab_id in tab_ids):
        raise InputRejected("untaggedViews must be a list of tab ids")
    return {tab_id for tab_id in tab_ids if tab_id in tabs}


def _blank_tab_entry() -> Dict[str, object]:
    return {
        "searchQuery": "",
        "scrollY": 0,
        "anchorRootId": None,
        "scrollAnchor": None,
        "sortMode": SORT_MODE_NORMAL,
    }


def _is_uuid_string(value: str) -> bool:
    if not isinstance(value, str):
        return False
    if not value:
        return False
    if _UUID_RE.match(value) is None:
        return False
    return True


# --- Views (multi-view editing step 2, 2026-11-14) ------------------------------------------------

# What each tab keeps for every view; its scroll (_TAB_SCROLL_KEYS) is each view's own.
_SHARED_TAB_KEYS = ("searchQuery", "sortMode")
# The saved state with views; saved before them, it had one place (_apply_snapshot_locked).
_VIEWS_FORMAT = 2
_VIEWS_STATE_KEYS = (
    "format", "tabs", "tabOrder", "dateFilters", "fileFilters", "untaggedViews", "views", "pageOwners",
    "lastUsedTabId", "unclaimedPlace", "version",
)
_SAVED_PLACE_KEYS = ("activeTabId", "scroll", "referenceViews", "treeShown", "usedAt")
# 0.30.0 and 0.30.1 saved with each place what its browser held of each search, to tell which
# searches a saved copy changed. A view now asks for a search by name (set_search), so the record
# is read and dropped.
_SAVED_PLACE_KEYS_WITH_KNOWN_SEARCH = frozenset(_SAVED_PLACE_KEYS) | {"knownSearch"}
# The owner of the pages saved before views, until the first view to ask takes them.
_UNCLAIMED = ""
# A view unused this long is forgotten, with its pages (multi-view note §9: weeks, not hours).
_DAYS_A_VIEW_IS_KEPT = 30
_SECONDS_PER_DAY = 24 * 60 * 60
_VIEW_FORGOTTEN_AFTER_SECONDS = _DAYS_A_VIEW_IS_KEPT * _SECONDS_PER_DAY


def _require_view_id(view_id: object) -> None:
    if not isinstance(view_id, str) or view_id == "" or len(view_id) > MAX_TAB_ID_LENGTH:
        raise InputRejected("X-Metalist-Tab-Id must name the view")


# A search of note ids alone, one or several joined by OR: a reference page's.
_NOTE_ID_SEARCH_RE = re.compile(
    r"^\s*[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"(?:\s+OR\s+[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})*\s*$",
    re.IGNORECASE,
)


def _is_note_id_search(search: object) -> bool:
    assert isinstance(search, str), "a tab's search is text"
    return _NOTE_ID_SEARCH_RE.match(search) is not None


def _blank_scroll() -> Dict[str, object]:
    return {"scrollY": 0, "anchorRootId": None, "scrollAnchor": None}


def _blank_shared_tab() -> Dict[str, object]:
    return {"searchQuery": "", "sortMode": SORT_MODE_NORMAL}


def _new_place(*, active_tab_id: str) -> Dict[str, object]:
    return {"activeTabId": active_tab_id, "scroll": {}, "referenceViews": {}, "treeShown": False, "usedAt": 0.0}


def _used_at(place: Dict[str, object]) -> float:
    used_at = place["usedAt"]
    assert isinstance(used_at, (int, float)), "a place says when it was used"
    return float(used_at)


def _place_scroll(place: Dict[str, object]) -> Dict[str, Dict[str, object]]:
    scroll = place["scroll"]
    assert isinstance(scroll, dict), "a place keeps its scroll by tab"
    return scroll


def _place_reference_views(place: Dict[str, object]) -> Dict[str, Dict[str, object]]:
    views = place["referenceViews"]
    assert isinstance(views, dict), "a place keeps its reference pages"
    return views


def _normalize_shared_tabs(tabs: object) -> Dict[str, Dict[str, object]]:
    if not isinstance(tabs, dict) or not tabs:
        raise RuntimeError("tab-state JSON tabs must be a non-empty object")
    normalized: Dict[str, Dict[str, object]] = {}
    for tab_id, entry in tabs.items():
        if not isinstance(tab_id, str) or not _is_uuid_string(tab_id) or not isinstance(entry, dict):
            raise RuntimeError("tab-state JSON tabs must map tab ids to tabs")
        search = entry["searchQuery"]
        if not isinstance(search, str):
            raise RuntimeError("tab-state JSON searchQuery must be text")
        normalized[tab_id] = {
            "searchQuery": search,
            "sortMode": _normalize_tab_sort_mode(entry["sortMode"], from_storage=True),
        }
    return normalized


def _load_place(saved: object, tabs: Dict[str, Dict[str, object]]) -> Dict[str, object]:
    """A view's place as saved, less what refers to tabs that are gone."""
    if not isinstance(saved, dict) or set(saved) not in (set(_SAVED_PLACE_KEYS), _SAVED_PLACE_KEYS_WITH_KNOWN_SEARCH):
        raise RuntimeError(f"a saved place must have exactly {_SAVED_PLACE_KEYS}")
    active = saved["activeTabId"]
    tree_shown = saved["treeShown"]
    used_at = saved["usedAt"]
    scroll = saved["scroll"]
    if not isinstance(active, str) or not isinstance(tree_shown, bool) or not isinstance(used_at, (int, float)):
        raise RuntimeError("a saved place's tab, tree and time must be a tab id, true or false and a time")
    if not isinstance(scroll, dict):
        raise RuntimeError("a saved place's scroll must be an object")
    place = _new_place(active_tab_id=active)
    place["treeShown"] = tree_shown
    place["usedAt"] = float(used_at)
    place["scroll"] = {
        tab_id: {key: entry[key] for key in _TAB_SCROLL_KEYS}
        for tab_id, entry in scroll.items() if tab_id in tabs and isinstance(entry, dict)
    }
    place["referenceViews"] = _normalize_reference_views(saved["referenceViews"], tabs, from_storage=True)
    return place


class TabStateStore:
    """Server-owned tab state with namespace-scoped persistence in SQLite.

    Two parts (multi-view editing step 2, 2026-11-14; docs/design/multi-view-editing.md
    §2 and §10): shared by every view, the search contexts (their order, search, sort, date range,
    Files filter, Untagged); each view's own (a browser tab, the installed phone app, named by its
    X-Metalist-Tab-Id), its place: the context it shows, its scroll in each, its reference pages
    and whether the folder tree shows. A reference page belongs to the view that opened it and is
    never listed or sent to another."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._encrypted_state_json: Optional[str] = None
        self._encrypted_state_nonce: Optional[bytes] = None
        self._encrypted_state_tag: Optional[bytes] = None
        # Shared: each tab's search and sort order.
        self._tabs: Dict[str, Dict[str, object]] = {}
        self._tab_order: List[str] = []
        self._date_filters: Dict[str, Dict[str, str]] = {}
        self._file_filters: Dict[str, str] = {}
        self._untagged_views: Set[str] = set()
        # Each view's place, by view id.
        self._views: Dict[str, Dict[str, object]] = {}
        # The reference pages' tabs, by the view they belong to (_UNCLAIMED: saved before views).
        self._page_owners: Dict[str, str] = {}
        # The search context any view showed last: a new view starts on it.
        self._last_used_tab_id = ""
        # The place saved before views (0.30.0): the first view to ask takes it.
        self._unclaimed_place: Optional[Dict[str, object]] = None
        # The version at which each tab's scroll last started again at the top.
        self._scroll_restarted_at_version: Dict[str, int] = {}
        # Tabs deleted or closed: a view's save made before it heard so may still name them, and
        # is taken without them (update).
        self._gone_tab_ids: Set[str] = set()
        # Reference pages closed because their notes were deleted (was_closed_with_its_notes).
        self._closed_page_tab_ids: Set[str] = set()
        # The version at which pages last closed so: each view of the list carries it, and the
        # browser takes the server's tabs again when it has risen (adoptClosedReferencePages).
        self._pages_closed_at_version = 0
        # Rises, for a view, when what every view shares changes (the search contexts, their
        # order, searches, sorts and filters, and the searches the other views are typing), not
        # when a view scrolls or moves: each view reads its own from the status it polls and takes
        # the contexts again (multi-view editing step 3, cases 11 to 14). Kept per view because a
        # view's own search lock is no news to it: counted for every view alike, the lock a view
        # took and released made that view take the contexts again each time (2026-11-15).
        self._shared_revisions: Dict[str, int] = {}
        self._shared_fingerprints: Dict[str, str] = {}
        # Each view's shared revision as the request being answered found it: its answer says
        # whether it was the only change since (searchContextsRevision), so a view takes no change
        # of its own for another view's.
        self._shared_revisions_before: Dict[str, int] = {}
        self._install_default_state_locked(version=0)

    def bootstrap(self, *, connection) -> None:
        row = fetch_tab_state_row(connection)
        with self._lock:
            if row is None:
                self._clear_encrypted_state_locked()
                self._install_default_state_locked(version=0)
                return

            state_json = row["state_json"]
            nonce = row["state_encryption_nonce"]
            tag = row["state_encryption_tag"]
            if not isinstance(state_json, str):
                raise TypeError("tab_state.state_json must be a string")
            if (nonce is None) != (tag is None):
                raise RuntimeError(
                    "tab_state row has incomplete encryption metadata: "
                    f"nonce={nonce is not None} tag={tag is not None}"
                )

            if nonce is None:
                self._load_state_json_locked(state_json)
                self._clear_encrypted_state_locked()
                return

            self._encrypted_state_json = state_json
            self._encrypted_state_nonce = nonce
            self._encrypted_state_tag = tag
            self._install_default_state_locked(version=0)
            self._try_decrypt_locked(token="", require_success=False)

    def ensure_decrypted(self, *, token: str) -> None:
        if not isinstance(token, str):
            raise TypeError("token must be a string")
        with self._lock:
            self._try_decrypt_locked(token=token, require_success=True)

    def snapshot(self, *, view_id: str) -> Dict[str, object]:
        """This view's tabs: the shared search contexts with its own place in them."""
        with self._lock:
            self._try_decrypt_locked(token="", require_success=False)
            return self._snapshot_locked(view_id)

    def reset(self) -> None:
        with self._lock:
            next_version = self._version + 1
            self._clear_encrypted_state_locked()
            self._install_default_state_locked(version=next_version)

    def clear_persisted_state_for_tests(self) -> None:
        with begin_writer() as connection:
            delete_tab_state_row(connection)
        with self._lock:
            self._clear_encrypted_state_locked()
            self._install_default_state_locked(version=0)

    # --- Views -------------------------------------------------------------------------------

    def _place_locked(self, view_id: str) -> Dict[str, object]:
        """The view's place; a view not seen before starts on the search context used most
        recently, or takes the place saved before views."""
        _require_view_id(view_id)
        now = time()
        if view_id in self._views:
            place = self._views[view_id]
            place["usedAt"] = now
            return place
        self._forget_unused_views_locked(now)
        if self._unclaimed_place is not None:
            place = self._unclaimed_place
            self._unclaimed_place = None
            for tab_id, owner in list(self._page_owners.items()):
                if owner == _UNCLAIMED:
                    self._page_owners[tab_id] = view_id
        else:
            place = _new_place(active_tab_id=self._last_used_tab_id)
        place["usedAt"] = now
        self._views[view_id] = place
        return place

    def _forget_unused_views_locked(self, now: float) -> None:
        """A view unused for weeks is forgotten, with its reference pages (multi-view note §9)."""
        unused = [
            view_id for view_id, place in self._views.items()
            if now - _used_at(place) >= _VIEW_FORGOTTEN_AFTER_SECONDS
        ]
        for view_id in unused:
            del self._views[view_id]
            for tab_id in [tab_id for tab_id, owner in self._page_owners.items() if owner == view_id]:
                self._remove_tab_locked(tab_id)

    def _visible_tab_ids_locked(self, view_id: str) -> List[str]:
        """The view's tabs, in list order: every search context, and its own reference pages."""
        return [
            tab_id for tab_id in self._tab_order
            if tab_id not in self._page_owners or self._page_owners[tab_id] == view_id
        ]

    def _context_ids_locked(self) -> List[str]:
        return [tab_id for tab_id in self._tab_order if tab_id not in self._page_owners]

    def _active_tab_of_locked(self, view_id: str, place: Dict[str, object]) -> str:
        """The tab the view shows; one gone (deleted elsewhere) gives way to the search context
        used most recently, or the first."""
        active = place["activeTabId"]
        if active in self._visible_tab_ids_locked(view_id):
            assert isinstance(active, str), "a place's tab is an id"
            return active
        contexts = self._context_ids_locked()
        assert contexts, "the list always keeps a search context"
        replacement = contexts[0]
        if self._last_used_tab_id in contexts:
            replacement = self._last_used_tab_id
        place["activeTabId"] = replacement
        return replacement

    def _snapshot_locked(self, view_id: str) -> Dict[str, object]:
        """The view's tabs: the shared search contexts with its own place in them."""
        place = self._place_locked(view_id)
        active = self._active_tab_of_locked(view_id, place)
        visible = self._visible_tab_ids_locked(view_id)
        scroll = _place_scroll(place)
        tabs: Dict[str, Dict[str, object]] = {}
        for tab_id in visible:
            tab_scroll = _blank_scroll()
            if tab_id in scroll:
                tab_scroll = deepcopy(scroll[tab_id])
            tabs[tab_id] = {**self._tabs[tab_id], **tab_scroll}
        return {
            "activeTabId": active,
            "tabs": tabs,
            "tabOrder": visible,
            "referenceViews": deepcopy(place["referenceViews"]),
            "dateFilters": {tab_id: deepcopy(value) for tab_id, value in self._date_filters.items() if tab_id in tabs},
            "fileFilters": {tab_id: value for tab_id, value in self._file_filters.items() if tab_id in tabs},
            "treeShown": place["treeShown"],
            "untaggedViews": sorted(tab_id for tab_id in self._untagged_views if tab_id in tabs),
            "version": self._version,
            # Searches other views are typing: this view's search box waits (multi-view step 4).
            "searchLocks": edit_locks.search_locks_for(view_id=view_id),
            # What every view shares, before and after this request (live-changes-service.js).
            "searchContextsRevision": self._shared_revision_before_and_after_locked(view_id),
        }

    def shared_revision(self, *, view_id: str) -> int:
        """What every view shares, as view_id sees it: a number that rises when it changes, worked
        out when asked (a few dozen contexts at most), so no change, loaded or made, can slip past it."""
        with self._lock:
            return self._refresh_shared_revision_locked(view_id)

    def _shared_revision_before_and_after_locked(self, view_id: str) -> Dict[str, int]:
        after = self._refresh_shared_revision_locked(view_id)
        # A view heard from for the first time has no revision from before this request: nothing
        # of its own changed it.
        before = after
        if view_id in self._shared_revisions_before:
            before = self._shared_revisions_before[view_id]
        return {"before": before, "after": after}

    def _refresh_shared_revision_locked(self, view_id: str) -> int:
        fingerprint = self._shared_fingerprint_locked(view_id)
        if view_id not in self._shared_fingerprints:
            self._shared_fingerprints[view_id] = fingerprint
            self._shared_revisions[view_id] = 0
        elif fingerprint != self._shared_fingerprints[view_id]:
            self._shared_fingerprints[view_id] = fingerprint
            self._shared_revisions[view_id] += 1
        return self._shared_revisions[view_id]

    def _shared_fingerprint_locked(self, view_id: str) -> str:
        contexts = self._context_ids_locked()
        shared = {
            "order": contexts,
            "tabs": {tab_id: self._tabs[tab_id] for tab_id in contexts},
            "dateFilters": {tab_id: self._date_filters[tab_id] for tab_id in contexts if tab_id in self._date_filters},
            "fileFilters": {tab_id: self._file_filters[tab_id] for tab_id in contexts if tab_id in self._file_filters},
            "untagged": sorted(tab_id for tab_id in contexts if tab_id in self._untagged_views),
            # A search being typed in another view shows as locked in this one; its own is no news to it.
            "searchLocks": sorted(edit_locks.search_locks_for(view_id=view_id)),
        }
        return json.dumps(shared, separators=(",", ":"), sort_keys=True)

    def _remove_tab_locked(self, tab_id: str) -> None:
        """A tab gone from the list, and from every view's place."""
        del self._tabs[tab_id]
        self._tab_order.remove(tab_id)
        if tab_id in self._page_owners:
            del self._page_owners[tab_id]
        for place in self._places_locked():
            scroll = _place_scroll(place)
            if tab_id in scroll:
                del scroll[tab_id]
        self._forget_tab_settings_locked(tab_id)
        self._gone_tab_ids.add(tab_id)
        if self._last_used_tab_id == tab_id:
            self._last_used_tab_id = ""

    def _places_locked(self) -> List[Dict[str, object]]:
        """Every view's place, the one saved before views included."""
        places = list(self._views.values())
        if self._unclaimed_place is not None:
            places.append(self._unclaimed_place)
        return places

    def _renormalize_reference_views_locked(self) -> None:
        """Each view's reference pages, without those whose tab or search context is gone."""
        for place in self._places_locked():
            place["referenceViews"] = _normalize_reference_views(
                place["referenceViews"], self._tabs, from_storage=False,
            )

    # --- Tabs --------------------------------------------------------------------------------

    def create_tab(self, *, view_id: str, copy_from_tab_id: str, copies_view: bool, is_page: bool) -> Dict[str, object]:
        """A new tab after copy_from_tab_id. A duplicate (copies_view) copies everything that
        decides which notes the tab shows and their order; a new tab starts with nothing
        (the maintainer, 2026-11-02, docs/ui/state-handling.md). A reference page (is_page)
        belongs to this view alone."""
        if not isinstance(copies_view, bool) or not isinstance(is_page, bool):
            raise TypeError("copies_view and is_page must be bools")
        if not isinstance(copy_from_tab_id, str) or not copy_from_tab_id:
            raise InputRejected("copyFromTabId must be a non-empty string")
        if not _is_uuid_string(copy_from_tab_id):
            raise InputRejected("copyFromTabId must be a UUID string")

        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            place = self._place_locked(view_id)
            if copy_from_tab_id not in self._visible_tab_ids_locked(view_id):
                raise InputRejected("copyFromTabId must reference an existing tab")
            if len(self._tabs) >= _MAX_TABS:
                raise InputRejected(f"max tabs reached ({_MAX_TABS})")

            new_tab_id = self._new_tab_id()
            while new_tab_id in self._tabs:
                new_tab_id = self._new_tab_id()

            if copies_view:
                self._tabs[new_tab_id] = deepcopy(self._tabs[copy_from_tab_id])
                scroll = _place_scroll(place)
                if copy_from_tab_id in scroll:
                    scroll[new_tab_id] = deepcopy(scroll[copy_from_tab_id])
                if copy_from_tab_id in self._date_filters:
                    self._date_filters[new_tab_id] = deepcopy(self._date_filters[copy_from_tab_id])
                if copy_from_tab_id in self._file_filters:
                    self._file_filters[new_tab_id] = self._file_filters[copy_from_tab_id]
                if copy_from_tab_id in self._untagged_views:
                    self._untagged_views.add(new_tab_id)
            else:
                self._tabs[new_tab_id] = _blank_shared_tab()
            if is_page:
                self._page_owners[new_tab_id] = view_id
            self._tab_order.append(new_tab_id)
            self._version += 1
            self._persist_locked(connection=None, encryption_service=None, force_plaintext=False)
            snapshot = self._snapshot_locked(view_id)
            snapshot["newTabId"] = new_tab_id
            return snapshot

    def delete_tab(self, *, view_id: str, tab_id: str) -> Dict[str, object]:
        if not isinstance(tab_id, str) or not tab_id:
            raise InputRejected("tabId must be a non-empty string")
        if not _is_uuid_string(tab_id):
            raise InputRejected("tabId must be a UUID string")

        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            place = self._place_locked(view_id)
            visible = self._visible_tab_ids_locked(view_id)
            if tab_id not in visible:
                raise InputRejected("tabId must reference an existing tab")
            if tab_id not in self._page_owners and len(self._context_ids_locked()) <= 1:
                raise InputRejected("cannot delete the last remaining tab")

            if place["activeTabId"] == tab_id:
                index = visible.index(tab_id)
                remaining = [other for other in visible if other != tab_id]
                place["activeTabId"] = remaining[min(index, len(remaining) - 1)]
            self._remove_tab_locked(tab_id)
            self._renormalize_reference_views_locked()
            self._version += 1
            self._persist_locked(connection=None, encryption_service=None, force_plaintext=False)
            return self._snapshot_locked(view_id)

    def _forget_tab_settings_locked(self, tab_id: str) -> None:
        """What is kept beside a tab that is gone."""
        if tab_id in self._date_filters:
            del self._date_filters[tab_id]
        if tab_id in self._file_filters:
            del self._file_filters[tab_id]
        self._untagged_views.discard(tab_id)
        if tab_id in self._scroll_restarted_at_version:
            del self._scroll_restarted_at_version[tab_id]

    def close_pages_whose_notes_are_gone(self, *, note_exists: Callable[[str], bool]) -> bool:
        """Close each reference page none of whose notes exist any more, in every view, with the
        pages opened from it: its search context goes back to its search (`foo > bar`, bar
        deleted, reads `foo`; the maintainer, 2026-11-14). A view shown one shows the search it
        was opened from. Returns whether any closed."""
        if not callable(note_exists):
            raise TypeError("note_exists must be callable")
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            places = self._places_locked()
            closing = {
                tab_id for place in places for tab_id, view in _place_reference_views(place).items()
                if not any(note_exists(note_id) for note_id in _reference_note_ids(view))
            }
            if not closing:
                return False
            is_growing = True
            while is_growing:
                opened_from_closing = {
                    tab_id for place in places for tab_id, view in _place_reference_views(place).items()
                    if tab_id not in closing and view["fromTabId"] in closing
                }
                closing |= opened_from_closing
                is_growing = len(opened_from_closing) > 0
            for place in places:
                if place["activeTabId"] in closing:
                    place["activeTabId"] = self._search_shown_after_closing_locked(place, closing)
            for tab_id in closing:
                self._remove_tab_locked(tab_id)
            self._renormalize_reference_views_locked()
            self._closed_page_tab_ids |= closing
            self._version += 1
            self._pages_closed_at_version = self._version
            self._persist_locked(connection=None, encryption_service=None, force_plaintext=False)
            return True

    def was_closed_with_its_notes(self, *, tab_id: str) -> bool:
        """A reference page closed because its notes were deleted: the browser may still ask for
        its view once, before it hears so."""
        with self._lock:
            return tab_id in self._closed_page_tab_ids

    def pages_closed_at_version(self) -> int:
        with self._lock:
            return self._pages_closed_at_version

    def _search_shown_after_closing_locked(self, place: Dict[str, object], closing: Set[str]) -> str:
        """The search a closed page was opened from; the first search context when that is gone
        as well."""
        active = place["activeTabId"]
        views = _place_reference_views(place)
        if active in views:
            origin_tab_id = _origin_tab_id(views[active])
            if origin_tab_id in self._tabs and origin_tab_id not in closing:
                return origin_tab_id
        contexts = [tab_id for tab_id in self._context_ids_locked() if tab_id not in closing]
        assert contexts, "closing pages leaves the search contexts they were opened from"
        return contexts[0]

    def update(
        self,
        *,
        view_id: str,
        tabs: Dict[str, Dict[str, object]],
        tab_order: List[str],
        reference_views: object,
        read_at_version: int,
    ) -> Dict[str, object]:
        """Save a view's copy of its tabs, read when its state was at read_at_version (the last
        version it received): its reference pages. The tab it shows, a search, the order of the
        tabs and its scroll in each are never taken from the copy: the view asks for each by name
        (show_tab, set_search, move_tab, set_scroll), so no copy, late or stale, can move the view
        back, put an old search back or undo another view's move. Tabs the copy leaves out are kept."""
        if not isinstance(read_at_version, int) or read_at_version < 0:
            raise InputRejected("version must be a non-negative integer")
        normalized_tabs = self._normalize_tabs(tabs, from_storage=False)
        # The copy's order is checked as part of the copy, and not taken (move_tab).
        self._normalize_tab_order(tab_order, normalized_tabs)
        normalized_reference_views = _normalize_reference_views(
            reference_views, normalized_tabs, from_storage=False,
        )
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            place = self._place_locked(view_id)
            # Saved before the view heard that tabs were deleted or pages closed: taken without them.
            gone_meanwhile = set(normalized_tabs) & self._gone_tab_ids
            if gone_meanwhile:
                normalized_tabs = {tab_id: entry for tab_id, entry in normalized_tabs.items() if tab_id not in gone_meanwhile}
                normalized_reference_views = _normalize_reference_views(
                    normalized_reference_views, normalized_tabs, from_storage=False,
                )
            # The tabs are the server's: a copy that leaves one out takes none away (delete_tab
            # does), whatever version it names. A view's version rises with the answers to its own
            # changes, which bring it no tab another view made meanwhile (2026-11-15: a save raced
            # the view's own new tab; 2026-11-17: a save after a typed search left out another
            # view's new context). A tab the server never had is no tab of its.
            if not set(normalized_tabs) <= set(self._visible_tab_ids_locked(view_id)):
                raise InputRejected("tab ids mismatch; use tab-state new/delete endpoints")
            for tab_id in normalized_reference_views:
                if tab_id in self._page_owners and self._page_owners[tab_id] != view_id:
                    raise InputRejected("a reference page belongs to another view")

            was = (
                deepcopy(self._tabs), list(self._tab_order), deepcopy(place["scroll"]),
                deepcopy(place["referenceViews"]), place["activeTabId"], dict(self._page_owners), self._last_used_tab_id,
            )
            # A tab of note ids the view took as a page (adoptOrphanReferenceTabs) becomes its own.
            for tab_id in normalized_reference_views:
                if tab_id not in self._page_owners:
                    self._page_owners[tab_id] = view_id
            place["referenceViews"] = normalized_reference_views
            # A view saving its place is using the context it shows (a new view starts there).
            shown = self._active_tab_of_locked(view_id, place)
            if shown not in self._page_owners:
                self._last_used_tab_id = shown
            now = (
                self._tabs, self._tab_order, place["scroll"], place["referenceViews"], place["activeTabId"],
                self._page_owners, self._last_used_tab_id,
            )
            # Scroll persistence posts about once a second; unchanged state must not re-encrypt
            # and rewrite the row. The view accepts the same version.
            if was == now:
                return self._snapshot_locked(view_id)
            self._version += 1
            self._persist_locked(connection=None, encryption_service=None, force_plaintext=False)
            return self._snapshot_locked(view_id)

    def set_scroll(self, *, view_id: str, tab_id: str, scroll: Dict[str, object], read_at_version: int) -> Dict[str, object]:
        """This view's scroll in tab_id is now scroll (_TAB_SCROLL_KEYS), measured when the view's
        state was at read_at_version: the one way a view's scroll in a tab changes
        (docs/future-plans/one-writer-refactoring.md, idea 1). A scroll measured before the tab's
        scroll restarted (another search, sort order or filter) belongs to the notes it showed
        then, and is not taken."""
        if not isinstance(tab_id, str) or not tab_id:
            raise InputRejected("tabId must be a non-empty string")
        if not isinstance(read_at_version, int) or read_at_version < 0:
            raise InputRejected("version must be a non-negative integer")
        if not isinstance(scroll, dict) or set(scroll) != set(_TAB_SCROLL_KEYS):
            raise InputRejected("a scroll is its scrollY, scrollAnchor and anchorRootId")
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            place = self._place_locked(view_id)
            # Measured before the view heard the tab was deleted or its page closed: nothing to
            # change, as for a search (set_search).
            if tab_id in self._gone_tab_ids:
                snapshot = self._snapshot_locked(view_id)
                snapshot["changed"] = False
                return snapshot
            if tab_id not in self._visible_tab_ids_locked(view_id):
                raise InputRejected("tabId must reference an existing tab")
            # Checked as a tab's scroll is (the tab's own search and sort order are not read).
            as_tab = self._normalize_tabs({tab_id: {**self._tabs[tab_id], **scroll}}, from_storage=False)[tab_id]
            new_scroll = {key: as_tab[key] for key in _TAB_SCROLL_KEYS}
            is_restarted_since = (
                tab_id in self._scroll_restarted_at_version
                and read_at_version < self._scroll_restarted_at_version[tab_id]
            )
            scrolls = _place_scroll(place)
            old_scroll = _blank_scroll()
            if tab_id in scrolls:
                old_scroll = scrolls[tab_id]
            # A view saving its scroll is using the context it shows (a new view starts there).
            shown = self._active_tab_of_locked(view_id, place)
            uses_another_context = shown not in self._page_owners and shown != self._last_used_tab_id
            changed = not is_restarted_since and new_scroll != old_scroll
            if changed:
                scrolls[tab_id] = new_scroll
            if uses_another_context:
                self._last_used_tab_id = shown
            # Scroll is saved about once a second: an unchanged one must not re-encrypt and
            # rewrite the row.
            if changed or uses_another_context:
                self._version += 1
                self._persist_locked(connection=None, encryption_service=None, force_plaintext=False)
            snapshot = self._snapshot_locked(view_id)
            snapshot["changed"] = changed
            return snapshot

    def get_sort_mode(self, *, tab_id: str) -> str:
        if not isinstance(tab_id, str):
            raise TypeError("tab_id must be a string")
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            if tab_id not in self._tabs:
                raise InputRejected("tab_id must reference an existing tab")
            value = self._tabs[tab_id]["sortMode"]
            return normalize_sort_mode(value)

    def get_date_filter(self, *, tab_id: str) -> RootDateFilter | None:
        """The tab's date range filter, or None when it shows every date."""
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            if tab_id not in self._tabs:
                raise InputRejected("tab_id must reference an existing tab")
            if tab_id not in self._date_filters:
                return None
            return root_date_filter_from_payload(self._date_filters[tab_id])

    def get_file_filter(self, *, tab_id: str) -> str | None:
        """The tab's Files filter kind, or None when it shows every note."""
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            if tab_id not in self._tabs:
                raise InputRejected("tab_id must reference an existing tab")
            if tab_id not in self._file_filters:  # shockharness: ignore[DEF002] reason="a tab without a Files filter shows every note: None is that, as get_date_filter's None is every date"
                return None
            return self._file_filters[tab_id]

    def set_file_filter(self, *, view_id: str, tab_id: str, file_filter: str | None) -> Dict[str, object]:
        """Set (or, with None, remove) a tab's Files filter. Like a date range it changes
        what the view shows, so the tab's scroll starts again at the top. Removing it
        ends the File size order, which means nothing without it."""
        if not isinstance(tab_id, str) or not tab_id:
            raise InputRejected("tabId must be a non-empty string")
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            if tab_id not in self._tabs:
                raise InputRejected("tabId must reference an existing tab")
            current = None
            if tab_id in self._file_filters:
                current = self._file_filters[tab_id]
            changed = current != file_filter
            if changed:
                if file_filter is None:
                    del self._file_filters[tab_id]
                    if base_sort_mode(self._tabs[tab_id]["sortMode"]) == SORT_MODE_FILE_SIZE:
                        self._tabs[tab_id]["sortMode"] = SORT_MODE_NORMAL
                else:
                    self._file_filters[tab_id] = make_file_filter(file_filter)
                self._restart_tab_scroll_locked(tab_id)
            snapshot = self._snapshot_locked(view_id)
            snapshot["changed"] = changed
            return snapshot

    def set_tree_shown(self, *, view_id: str, is_shown: bool) -> Dict[str, object]:
        """The folders tab: the tree shown or hidden in this view, nothing else (no search context
        changes; folders-tab-and-multiple-folders.md §1). Each view's own (multi-view note §2)."""
        if not isinstance(is_shown, bool):
            raise InputRejected("isShown must be true or false")
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            place = self._place_locked(view_id)
            if place["treeShown"] != is_shown:
                place["treeShown"] = is_shown
                self._version += 1
                self._persist_locked(connection=None, encryption_service=None, force_plaintext=False)
            return self._snapshot_locked(view_id)

    def choose_folder(self, *, view_id: str, tab_id: str, folder: str, adds: bool) -> Dict[str, object]:
        """A folder clicked in the tree (NO_FOLDER for the top, `/`). A click: the tab searches that
        folder, its search before replaced; the top empties it (folder-tags-in-search.md §2). With
        adds (⌘-click, Ctrl-click off the Mac): that folder added to the search, or taken out when
        it is in it; the top takes every folder out; the rest of the search stays
        (folders-tab-and-multiple-folders.md §2). Shown from the top."""
        if not isinstance(tab_id, str) or not _is_uuid_string(tab_id):
            raise InputRejected("tabId must be a UUID string")
        if folder != NO_FOLDER and not is_folder_tag(folder):
            raise InputRejected(f"{folder} is not a folder")
        if not isinstance(adds, bool):
            raise InputRejected("adds must be true or false")
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            if tab_id not in self._tabs:
                raise InputRejected("tabId must reference an existing tab")
            search = self._tabs[tab_id]["searchQuery"]
            assert isinstance(search, str), "a tab's search is text"
            chosen = folder
            if adds:
                chosen = toggle_folder_in_search(search, folder)
            self._tabs[tab_id]["searchQuery"] = chosen
            # Persists, with the new version.
            self._restart_tab_scroll_locked(tab_id)
            # The browser takes the whole answer (keyboard-events.js, chooseFolder).
            return self._snapshot_locked(view_id)

    def set_untagged_view(self, *, view_id: str, tab_id: str, is_untagged_view: bool) -> Dict[str, object]:
        """Show the tab's untagged notes, or (False) its search again. Like a Files filter
        it changes what the view shows, so the tab's scroll starts again at the top."""
        if not isinstance(tab_id, str) or not tab_id:
            raise InputRejected("tabId must be a non-empty string")
        if not isinstance(is_untagged_view, bool):
            raise TypeError("is_untagged_view must be a bool")
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            if tab_id not in self._tabs:
                raise InputRejected("tabId must reference an existing tab")
            changed = (tab_id in self._untagged_views) != is_untagged_view
            if changed:
                if is_untagged_view:
                    self._untagged_views.add(tab_id)
                else:
                    self._untagged_views.remove(tab_id)
                self._restart_tab_scroll_locked(tab_id)
            snapshot = self._snapshot_locked(view_id)
            snapshot["changed"] = changed
            return snapshot

    def _restart_tab_scroll_locked(self, tab_id: str) -> None:
        """The tab shows other notes now: every view's scroll in it starts again at the top."""
        for place in self._places_locked():
            scroll = _place_scroll(place)
            if tab_id in scroll:
                del scroll[tab_id]
        self._version += 1
        self._scroll_restarted_at_version[tab_id] = self._version
        self._persist_locked(connection=None, encryption_service=None, force_plaintext=False)

    def set_date_filter(self, *, view_id: str, tab_id: str, date_filter: RootDateFilter | None) -> Dict[str, object]:
        """Set (or, with None, remove) a tab's date range filter. Like a sort order it
        changes what the view shows, so the tab's scroll starts again at the top."""
        if not isinstance(tab_id, str) or not tab_id:
            raise InputRejected("tabId must be a non-empty string")
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            if tab_id not in self._tabs:
                raise InputRejected("tabId must reference an existing tab")
            had_filter = tab_id in self._date_filters
            if date_filter is None:
                changed = had_filter
                if changed:
                    del self._date_filters[tab_id]
            else:
                next_payload = root_date_filter_payload(date_filter)
                changed = True
                if had_filter:
                    changed = self._date_filters[tab_id] != next_payload
                if changed:
                    self._date_filters[tab_id] = next_payload
            if changed:
                self._restart_tab_scroll_locked(tab_id)
            snapshot = self._snapshot_locked(view_id)
            snapshot["changed"] = changed
            return snapshot

    def show_tab(self, *, view_id: str, tab_id: str) -> Dict[str, object]:
        """This view now shows tab_id, as it asks: the one way a view changes the tab it shows
        (docs/future-plans/one-writer-refactoring.md, idea 1). Its scroll in the tab comes with
        its copy (update), as before."""
        if not isinstance(tab_id, str) or not tab_id:
            raise InputRejected("tabId must be a non-empty string")
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            place = self._place_locked(view_id)
            # Asked before the view heard the tab was deleted or its page closed: nothing to
            # change, as for a search (set_search); the view shows what the server picked.
            if tab_id in self._gone_tab_ids:
                snapshot = self._snapshot_locked(view_id)
                snapshot["changed"] = False
                return snapshot
            if tab_id not in self._visible_tab_ids_locked(view_id):
                raise InputRejected("tabId must reference an existing tab")
            changed = self._active_tab_of_locked(view_id, place) != tab_id
            if changed:
                place["activeTabId"] = tab_id
                if tab_id not in self._page_owners:
                    self._last_used_tab_id = tab_id
                self._version += 1
                self._persist_locked(connection=None, encryption_service=None, force_plaintext=False)
            snapshot = self._snapshot_locked(view_id)
            snapshot["changed"] = changed
            return snapshot

    def move_tab(self, *, view_id: str, tab_id: str, to_tab_id: str) -> Dict[str, object]:
        """Tab tab_id now sits where to_tab_id was, as this view dragged it: the one way the order
        of the tabs changes (docs/future-plans/one-writer-refactoring.md, idea 1). Moved down it
        lands right after to_tab_id, moved up right before it, so the tabs this view does not
        see (other views' reference pages) and the ones it has not heard of keep their places."""
        for name, value in (("tabId", tab_id), ("toTabId", to_tab_id)):
            if not isinstance(value, str) or not value:
                raise InputRejected(f"{name} must be a non-empty string")
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            self._place_locked(view_id)
            visible = self._visible_tab_ids_locked(view_id)
            # Asked before the view heard a tab was deleted or its page closed: nothing to move,
            # as for a search (set_search).
            is_gone_meanwhile = bool({tab_id, to_tab_id} & self._gone_tab_ids)
            for name, value in (("tabId", tab_id), ("toTabId", to_tab_id)):
                if value not in visible and value not in self._gone_tab_ids:
                    raise InputRejected(f"{name} must reference an existing tab")
            changed = not is_gone_meanwhile and tab_id != to_tab_id
            if changed:
                is_moved_down = self._tab_order.index(tab_id) < self._tab_order.index(to_tab_id)
                self._tab_order.remove(tab_id)
                slot = self._tab_order.index(to_tab_id)
                if is_moved_down:
                    slot += 1
                self._tab_order.insert(slot, tab_id)
                assert len(set(self._tab_order)) == len(self._tabs), "a move keeps every tab, once"
                self._version += 1
                self._persist_locked(connection=None, encryption_service=None, force_plaintext=False)
            snapshot = self._snapshot_locked(view_id)
            snapshot["changed"] = changed
            return snapshot

    def get_active_tab_id(self, *, view_id: str) -> str:
        """The tab this view shows."""
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            return self._active_tab_of_locked(view_id, self._place_locked(view_id))

    def search_context_with_search(self, *, view_id: str, search: str) -> str:
        """The search context, in list order, whose search has the same terms as this one, or ""
        for none: what a search link opens (docs/ready-to-build/search-links.md §3). Folder contexts
        are search contexts too (folder-tags-in-search.md §5); reference pages are never a search
        link's, nor is a context this view is on a page of: it shows the page, not its search, and
        stays there while the link opens the search in a new context (the maintainer, 2026-11-14)."""
        if not isinstance(search, str) or search.strip() == "":
            raise InputRejected("A search link needs a search.")
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            place = self._place_locked(view_id)
            on_a_page = {_origin_tab_id(view) for view in _place_reference_views(place).values()}
            for tab_id in self._context_ids_locked():
                if tab_id in on_a_page:
                    continue
                tab_search = self._tabs[tab_id]["searchQuery"]
                if not isinstance(tab_search, str):
                    raise RuntimeError("Tab searchQuery must be a string")
                if same_search(tab_search, search):
                    return tab_id
            return ""

    def get_search_query(self, *, tab_id: str) -> str:
        if not isinstance(tab_id, str):
            raise TypeError("tab_id must be a string")
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            if tab_id not in self._tabs:
                raise InputRejected("tab_id must reference an existing tab")
            value = self._tabs[tab_id]["searchQuery"]
            if not isinstance(value, str):
                raise RuntimeError("Tab searchQuery must be a string")
            return value

    def set_search(self, *, view_id: str, tab_id: str, search_query: str) -> Dict[str, object]:
        """The search of tab_id is now search_query, as this view asks: the one way a view changes
        a search (docs/future-plans/one-writer-refactoring.md, idea 1). Refused while another view
        types that search, else this view's to type for a few seconds (multi-view step 4, case 10).
        The view's scroll in the tab comes with its copy (update), as before."""
        if not isinstance(tab_id, str) or not tab_id:
            raise InputRejected("tabId must be a non-empty string")
        if not isinstance(search_query, str):
            raise InputRejected("searchQuery must be a string")
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            # Asked before the view heard the tab was deleted or its page closed: nothing to change,
            # as a copy saved then is taken without it (update).
            if tab_id in self._gone_tab_ids:
                snapshot = self._snapshot_locked(view_id)
                snapshot["changed"] = False
                return snapshot
            if tab_id not in self._visible_tab_ids_locked(view_id):
                raise InputRejected("tabId must reference an existing tab")
            changed = self._tabs[tab_id]["searchQuery"] != search_query
            if changed:
                edit_locks.note_search_typed(view_id=view_id, tab_id=tab_id)
                self._tabs[tab_id]["searchQuery"] = search_query
                self._version += 1
                self._persist_locked(connection=None, encryption_service=None, force_plaintext=False)
            snapshot = self._snapshot_locked(view_id)
            snapshot["changed"] = changed
            return snapshot

    def set_sort_mode(self, *, view_id: str, tab_id: str, sort_mode: str) -> Dict[str, object]:
        if not isinstance(tab_id, str) or not tab_id:
            raise InputRejected("tabId must be a non-empty string")
        normalized_sort_mode = normalize_sort_mode(sort_mode)

        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            if tab_id not in self._tabs:
                raise InputRejected("tabId must reference an existing tab")

            if base_sort_mode(normalized_sort_mode) == SORT_MODE_FILE_SIZE and tab_id not in self._file_filters:
                raise InputRejected("File size order needs Notes with Files on. Turn that on first.")

            entry = self._tabs[tab_id]
            changed = entry["sortMode"] != normalized_sort_mode
            if changed:
                entry["sortMode"] = normalized_sort_mode
                self._restart_tab_scroll_locked(tab_id)

            snapshot = self._snapshot_locked(view_id)
            snapshot["changed"] = changed
            return snapshot

    def rewrite_persisted_state(
        self,
        *,
        encryption_service: object | None,
        force_plaintext: bool,
        connection,
    ) -> None:
        if not isinstance(force_plaintext, bool):
            raise TypeError("force_plaintext must be a bool")
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            self._persist_locked(
                connection=connection,
                encryption_service=encryption_service,
                force_plaintext=force_plaintext,
            )

    def _install_default_state_locked(self, *, version: int) -> None:
        if not isinstance(version, int) or version < 0:
            raise TypeError("version must be a non-negative int")
        default_tab_id = self._new_tab_id()
        self._tabs = {default_tab_id: _blank_shared_tab()}
        self._tab_order = [default_tab_id]
        self._date_filters = {}
        self._file_filters = {}
        self._untagged_views = set()
        self._views = {}
        self._page_owners = {}
        self._last_used_tab_id = default_tab_id
        self._unclaimed_place = None
        self._scroll_restarted_at_version = {}
        self._gone_tab_ids = set()
        self._closed_page_tab_ids = set()
        self._version = version

    # --- Saved state -------------------------------------------------------------------------

    def _serialize_state_locked(self) -> str:
        places = {
            view_id: {key: place[key] for key in _SAVED_PLACE_KEYS}
            for view_id, place in self._views.items()
        }
        unclaimed: Optional[Dict[str, object]] = None
        if self._unclaimed_place is not None:
            unclaimed = {key: self._unclaimed_place[key] for key in _SAVED_PLACE_KEYS}
        state = {
            "format": _VIEWS_FORMAT,
            "tabs": self._tabs,
            "tabOrder": self._tab_order,
            "dateFilters": self._date_filters,
            "fileFilters": self._file_filters,
            "untaggedViews": sorted(self._untagged_views),
            "views": places,
            "pageOwners": self._page_owners,
            "lastUsedTabId": self._last_used_tab_id,
            "unclaimedPlace": unclaimed,
            "version": self._version,
        }
        return json.dumps(state, separators=(",", ":"), sort_keys=True)

    def _load_state_json_locked(self, payload: str) -> None:
        """Saved tabs: with views (2026-11-14 on), or as saved before them, one place, which then
        goes to the first view that asks."""
        if not isinstance(payload, str) or payload == "":
            raise InputRejected("tab-state payload must be a non-empty string")
        parsed = json.loads(payload)
        if not isinstance(parsed, dict):
            raise RuntimeError("tab-state JSON payload must be an object")
        if "views" in parsed:
            self._apply_views_state_locked(parsed)
            return
        self._apply_snapshot_locked(self._deserialize_snapshot_json(payload))

    def _apply_views_state_locked(self, parsed: Dict[str, object]) -> None:
        missing = [key for key in _VIEWS_STATE_KEYS if key not in parsed]
        if missing:
            raise RuntimeError(f"tab-state JSON payload missing required keys: {missing}")
        if parsed["format"] != _VIEWS_FORMAT:
            raise RuntimeError(f"tab-state format {parsed['format']!r} is not one this version reads")
        version = parsed["version"]
        if not isinstance(version, int) or version < 0:
            raise RuntimeError("tab-state JSON version must be a non-negative integer")
        tabs = _normalize_shared_tabs(parsed["tabs"])
        order = parsed["tabOrder"]
        if not isinstance(order, list) or sorted(order) != sorted(tabs) or len(set(order)) != len(order):
            raise RuntimeError("tab-state JSON tabOrder must list every tab once")
        owners = parsed["pageOwners"]
        if not isinstance(owners, dict) or not all(isinstance(owner, str) for owner in owners.values()):
            raise RuntimeError("tab-state JSON pageOwners must map tabs to views")
        views = parsed["views"]
        if not isinstance(views, dict):
            raise RuntimeError("tab-state JSON views must be an object")
        self._tabs = tabs
        self._tab_order = [str(tab_id) for tab_id in order]
        self._date_filters = _normalize_date_filters(parsed["dateFilters"], tabs)
        self._file_filters = _normalize_file_filters(parsed["fileFilters"], tabs)
        self._untagged_views = _normalize_untagged_views(parsed["untaggedViews"], tabs)
        self._page_owners = {tab_id: owner for tab_id, owner in owners.items() if tab_id in tabs}
        self._views = {view_id: _load_place(place, tabs) for view_id, place in views.items()}
        unclaimed = parsed["unclaimedPlace"]
        self._unclaimed_place = None
        if unclaimed is not None:
            self._unclaimed_place = _load_place(unclaimed, tabs)
        last_used = parsed["lastUsedTabId"]
        if not isinstance(last_used, str):
            raise RuntimeError("tab-state JSON lastUsedTabId must be a tab id")
        self._last_used_tab_id = last_used
        if last_used not in self._context_ids_locked():
            self._last_used_tab_id = self._context_ids_locked()[0]
        self._scroll_restarted_at_version = {}
        self._version = version

    def _apply_snapshot_locked(self, snapshot: Dict[str, object]) -> None:
        """Tabs saved before views (0.30.0 and earlier): one place, which the first view to ask
        takes, with its pages; the search contexts become the shared ones."""
        if not isinstance(snapshot, dict):
            raise TypeError("snapshot must be an object")
        active_tab_id = snapshot["activeTabId"]
        tabs = snapshot["tabs"]
        tab_order = snapshot["tabOrder"]
        version = snapshot["version"]
        if not isinstance(active_tab_id, str) or active_tab_id == "":
            raise RuntimeError("snapshot activeTabId must be a non-empty string")
        if not isinstance(version, int) or version < 0:
            raise RuntimeError("snapshot version must be a non-negative integer")
        if not isinstance(tabs, dict):
            raise RuntimeError("snapshot tabs must be an object")
        if not isinstance(tab_order, list):
            raise RuntimeError("snapshot tabOrder must be a list")
        normalized_tabs = self._normalize_tabs(tabs, from_storage=True)
        normalized_order = self._normalize_tab_order(tab_order, normalized_tabs)
        if active_tab_id not in normalized_tabs:
            raise RuntimeError("snapshot activeTabId must reference an existing tab")
        self._tabs = {
            tab_id: {key: entry[key] for key in _SHARED_TAB_KEYS} for tab_id, entry in normalized_tabs.items()
        }
        self._tab_order = normalized_order
        reference_views = _normalize_reference_views(snapshot["referenceViews"], self._tabs, from_storage=True)
        self._date_filters = _normalize_date_filters(snapshot["dateFilters"], normalized_tabs)
        self._file_filters = _normalize_file_filters(snapshot["fileFilters"], normalized_tabs)
        # Folder contexts were a kind of search context until 2026-11-11: each becomes an ordinary
        # one with the same search (folders-tab-and-multiple-folders.md §1), once, as the stored
        # state no longer names them once saved.
        folder_contexts = _normalize_folder_contexts(snapshot["folderContexts"], normalized_tabs)
        tree_shown = snapshot["treeShown"]
        assert isinstance(tree_shown, bool), "read as a bool from storage"
        # A folder kept apart from the search (before 2026-11-11) goes in front of its folder
        # context's search, once (folder-tags-in-search.md §2). One saved on a plain search
        # (before 2026-11-07) is dropped.
        for tab_id, folder in _normalize_folder_filters(snapshot["folderFilters"], normalized_tabs).items():
            if tab_id in folder_contexts:
                search = self._tabs[tab_id]["searchQuery"]
                assert isinstance(search, str), "a tab's search is text"
                self._tabs[tab_id]["searchQuery"] = f"{folder} {search}".strip()
        self._untagged_views = _normalize_untagged_views(snapshot["untaggedViews"], normalized_tabs)
        self._views = {}
        # Its pages, and the tabs of note ids alone no record claimed (0.29.0 left a page so when
        # its search context closed): the first view's, never shared contexts two views adopt.
        orphan_pages = {
            tab_id for tab_id, entry in self._tabs.items()
            if tab_id not in reference_views and _is_note_id_search(entry["searchQuery"])
        }
        self._page_owners = {tab_id: _UNCLAIMED for tab_id in [*reference_views, *orphan_pages]}
        # Every tab a page (0.29.0 closed the search context they came from): the list keeps a
        # search context, an empty one in front, which the pages are opened from.
        if not self._context_ids_locked():
            fresh_context = self._new_tab_id()
            self._tabs[fresh_context] = _blank_shared_tab()
            self._tab_order.insert(0, fresh_context)
        place = _new_place(active_tab_id=active_tab_id)
        place["scroll"] = {
            tab_id: {key: entry[key] for key in _TAB_SCROLL_KEYS} for tab_id, entry in normalized_tabs.items()
        }
        place["referenceViews"] = reference_views
        place["treeShown"] = tree_shown
        self._unclaimed_place = place
        self._last_used_tab_id = active_tab_id
        if active_tab_id in reference_views:
            self._last_used_tab_id = _origin_tab_id(reference_views[active_tab_id])
        if self._last_used_tab_id not in self._context_ids_locked():
            self._last_used_tab_id = self._context_ids_locked()[0]
        self._scroll_restarted_at_version = {}
        self._version = version

    def _try_decrypt_locked(self, *, token: str, require_success: bool) -> None:
        """Every request's first step under the lock: the state readable, and the shared revision
        as the request found it."""
        self._decrypt_locked(token=token, require_success=require_success)
        if self._encrypted_state_json is None:
            self._shared_revisions_before = {
                view_id: self._refresh_shared_revision_locked(view_id) for view_id in list(self._shared_fingerprints)
            }

    def _decrypt_locked(self, *, token: str, require_success: bool) -> None:
        if self._encrypted_state_json is None:
            return
        if self._encrypted_state_nonce is None or self._encrypted_state_tag is None:
            raise RuntimeError("encrypted tab-state payload missing nonce/tag")
        service = self._resolve_encryption_service(token=token, explicit_service=None)
        if service is None:
            if require_success:
                raise RuntimeError("tab-state decryption requires an active DEK")
            return
        plaintext = service.decrypt_from_storage(
            self._encrypted_state_json,
            self._encrypted_state_nonce,
            self._encrypted_state_tag,
        )
        if not isinstance(plaintext, str):
            raise TypeError("decrypted tab-state payload must be a string")
        self._load_state_json_locked(plaintext)
        self._clear_encrypted_state_locked()

    def rename_search_terms(self, *, rename: Callable[[str], str], connection) -> int:
        """Each search context's search, and every view's reference pages' queries, as `rename`
        returns them (meta_tag_renames.py, a one-time pass; Rename tag, rename_tag.py), saved with
        `connection` when any changed. Returns how many searches changed."""
        if not callable(rename):
            raise TypeError("rename must be callable")
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            changed = 0
            for tab in self._tabs.values():
                search_query = tab["searchQuery"]
                assert isinstance(search_query, str), "a tab's search is text"
                renamed = rename(search_query)
                if renamed != search_query:
                    tab["searchQuery"] = renamed
                    changed += 1
            for place in self._places_locked():
                for view in _place_reference_views(place).values():
                    reference_query = view["referenceQuery"]
                    scope = view["originScope"]
                    assert isinstance(reference_query, str) and isinstance(scope, dict), "a reference view is normalized"
                    # A reference view runs its tab's search, so both change together.
                    view["referenceQuery"] = rename(reference_query)
                    origin_query = scope["searchQuery"]
                    assert isinstance(origin_query, str), "an origin scope's search is text"
                    renamed = rename(origin_query)
                    if renamed != origin_query:
                        scope["searchQuery"] = renamed
                        changed += 1
            if changed == 0:
                return 0
            self._version += 1
            self._persist_locked(connection=connection, encryption_service=None, force_plaintext=False)
            return changed

    def _deserialize_snapshot_json(self, payload: str) -> Dict[str, object]:
        if not isinstance(payload, str) or payload == "":
            raise InputRejected("tab-state payload must be a non-empty string")
        parsed = json.loads(payload)
        if not isinstance(parsed, dict):
            raise RuntimeError("tab-state JSON payload must be an object")
        missing_keys = [key for key in ("activeTabId", "tabs", "tabOrder", "version") if key not in parsed]
        if missing_keys:
            raise RuntimeError(f"tab-state JSON payload missing required keys: {missing_keys}")
        active_tab_id = parsed["activeTabId"]
        tabs = parsed["tabs"]
        tab_order = parsed["tabOrder"]
        version = parsed["version"]
        if not isinstance(active_tab_id, str) or active_tab_id == "":
            raise RuntimeError("tab-state JSON activeTabId must be a non-empty string")
        if not isinstance(version, int) or version < 0:
            raise RuntimeError("tab-state JSON version must be a non-negative integer")
        if not isinstance(tab_order, list):
            raise RuntimeError("tab-state JSON tabOrder must be a list")
        # Tab state saved before reference views (or date or Files filters, Untagged views or,
        # before 2026-11-07, folders) were kept with the tabs has none.
        reference_views: object = {}
        if "referenceViews" in parsed:
            reference_views = parsed["referenceViews"]
        date_filters: object = {}
        if "dateFilters" in parsed:
            date_filters = parsed["dateFilters"]
        file_filters: object = {}
        if "fileFilters" in parsed:
            file_filters = parsed["fileFilters"]
        untagged_views: object = []
        if "untaggedViews" in parsed:
            untagged_views = parsed["untaggedViews"]
        folder_filters: object = {}
        if "folderFilters" in parsed:
            folder_filters = parsed["folderFilters"]
        # Saved with folder contexts (2026-11-07 to 2026-11-11): the tree shows when the active
        # tab was one, as it did (folders-tab-and-multiple-folders.md §1). Before them, hidden.
        folder_contexts = _normalize_folder_contexts(_stored_folder_contexts(parsed), tabs)
        tree_shown: object = active_tab_id in folder_contexts
        if "treeShown" in parsed:
            tree_shown = parsed["treeShown"]
        if not isinstance(tree_shown, bool):
            raise RuntimeError("tab-state JSON treeShown must be true or false")
        return {
            "activeTabId": active_tab_id,
            "tabs": self._normalize_tabs(tabs, from_storage=True),
            "tabOrder": [str(entry) for entry in tab_order],
            "referenceViews": reference_views,
            "dateFilters": date_filters,
            "fileFilters": file_filters,
            "folderFilters": folder_filters,
            "folderContexts": sorted(folder_contexts),
            "treeShown": tree_shown,
            "untaggedViews": untagged_views,
            "version": version,
        }

    def _persist_locked(
        self,
        *,
        connection,
        encryption_service: object | None,
        force_plaintext: bool,
    ) -> None:
        if not isinstance(force_plaintext, bool):
            raise TypeError("force_plaintext must be a bool")
        snapshot_json = self._serialize_state_locked()
        stored_json = snapshot_json
        nonce: Optional[bytes] = None
        tag: Optional[bytes] = None

        if not force_plaintext:
            service = self._resolve_encryption_service(
                token="",
                explicit_service=encryption_service,
            )
            if service is not None:
                stored_json, nonce, tag = service.encrypt_for_storage(snapshot_json)
            elif is_encryption_required():
                raise RuntimeError("tab-state persistence requires an active DEK")

        now = datetime.now(timezone.utc)
        if connection is not None:
            upsert_tab_state_row(
                connection,
                state_json=stored_json,
                state_encryption_nonce=nonce,
                state_encryption_tag=tag,
                updated_at=now,
            )
            return
        with begin_writer() as writer_connection:
            upsert_tab_state_row(
                writer_connection,
                state_json=stored_json,
                state_encryption_nonce=nonce,
                state_encryption_tag=tag,
                updated_at=now,
            )

    def _resolve_encryption_service(self, *, token: str, explicit_service: object | None):
        if explicit_service is not None:
            if explicit_service.dek is None:
                raise RuntimeError("explicit encryption service must have an active DEK")
            return explicit_service
        if token:
            return get_encryption_service_with_token(token)
        return get_encryption_service()

    def _clear_encrypted_state_locked(self) -> None:
        self._encrypted_state_json = None
        self._encrypted_state_nonce = None
        self._encrypted_state_tag = None

    def _new_tab_id(self) -> str:
        return str(uuid4())

    def _normalize_tab_order(self, incoming_order: List[str], tabs: Dict[str, Dict[str, object]]) -> List[str]:
        if not incoming_order:
            raise InputRejected("tabOrder must be a non-empty list")
        if len(incoming_order) != len(tabs):
            raise InputRejected("tabOrder must match tabs length")
        if len(incoming_order) > _MAX_TABS:
            raise InputRejected(f"tabOrder exceeds max tabs ({_MAX_TABS})")

        normalized: List[str] = []
        seen = set()
        for raw in incoming_order:
            tab_id = str(raw)
            if tab_id in seen:
                raise InputRejected("tabOrder contains duplicates")
            if tab_id not in tabs:
                raise InputRejected("tabOrder references unknown tab")
            seen.add(tab_id)
            normalized.append(tab_id)
        return normalized

    def _normalize_tabs(self, tabs: Dict[str, Dict[str, object]], *,
                        from_storage: bool) -> Dict[str, Dict[str, object]]:
        if not isinstance(tabs, dict) or not tabs:
            raise InputRejected("tabs must be a non-empty object")
        if len(tabs) > _MAX_TABS:
            raise InputRejected(f"tabs must contain at most {_MAX_TABS} entries")
        normalized: Dict[str, Dict[str, object]] = {}
        for key, value in tabs.items():
            tab_id = str(key)
            if not tab_id:
                raise InputRejected("tab ids must be non-empty strings")
            if not _is_uuid_string(tab_id):
                raise InputRejected("tab ids must be UUID strings")
            if not isinstance(value, dict):
                raise InputRejected("tab payload must be an object")
            if "searchQuery" not in value or "scrollY" not in value or "sortMode" not in value:
                raise InputRejected("tab payload missing required keys")
            search_query = value["searchQuery"]
            scroll_y = value["scrollY"]
            sort_mode = value["sortMode"]
            if not isinstance(search_query, str):
                raise InputRejected("searchQuery must be a string")
            if not isinstance(scroll_y, int) or scroll_y < 0:
                raise InputRejected("scrollY must be a non-negative integer")
            normalized_sort_mode = _normalize_tab_sort_mode(sort_mode, from_storage=from_storage)

            normalized_anchor_root_id: Optional[str] = None
            if "anchorRootId" in value:
                anchor_root_id = value["anchorRootId"]
            else:
                anchor_root_id = None
            if anchor_root_id is not None:
                if not isinstance(anchor_root_id, str) or anchor_root_id == "":
                    raise InputRejected("anchorRootId must be a non-empty string or null")
                normalized_anchor_root_id = anchor_root_id

            normalized_scroll_anchor: Optional[Dict[str, object]] = None
            if "scrollAnchor" in value:
                scroll_anchor = value["scrollAnchor"]
            else:
                scroll_anchor = None
            if scroll_anchor is not None:
                if not isinstance(scroll_anchor, dict):
                    raise InputRejected("scrollAnchor must be an object or null")

                if "anchorId" in scroll_anchor:
                    anchor_id = scroll_anchor["anchorId"]
                else:
                    anchor_id = None
                if "anchorBias" in scroll_anchor:
                    anchor_bias = scroll_anchor["anchorBias"]
                else:
                    anchor_bias = None
                if "intraOffset" in scroll_anchor:
                    intra_offset = scroll_anchor["intraOffset"]
                else:
                    intra_offset = None
                if "beltPrev" in scroll_anchor:
                    belt_prev = scroll_anchor["beltPrev"]
                else:
                    belt_prev = None
                if "beltNext" in scroll_anchor:
                    belt_next = scroll_anchor["beltNext"]
                else:
                    belt_next = None
                if "anchorSortKey" in scroll_anchor:
                    anchor_sort_key = scroll_anchor["anchorSortKey"]
                else:
                    anchor_sort_key = None

                if not isinstance(anchor_id, str) or not anchor_id:
                    raise InputRejected("scrollAnchor.anchorId must be a non-empty string")
                if anchor_bias not in ("center", "top"):
                    raise InputRejected("scrollAnchor.anchorBias must be 'center' or 'top'")
                if not isinstance(intra_offset, int) or intra_offset < 0:
                    raise InputRejected("scrollAnchor.intraOffset must be a non-negative integer")
                if not isinstance(belt_prev, list) or not isinstance(belt_next, list):
                    raise InputRejected("scrollAnchor belt arrays must be lists")

                def _normalize_belt(payload: List[object]) -> List[str]:
                    return [entry for entry in payload if isinstance(entry, str) and entry]

                normalized_prev = _normalize_belt(belt_prev)
                normalized_next = _normalize_belt(belt_next)

                if not isinstance(anchor_sort_key, dict):
                    raise InputRejected("scrollAnchor.anchorSortKey must be an object")
                if "domIndex" in anchor_sort_key:
                    dom_index = anchor_sort_key["domIndex"]
                else:
                    dom_index = None
                if not isinstance(dom_index, int) or dom_index < 0:
                    raise InputRejected("scrollAnchor.anchorSortKey.domIndex must be a non-negative integer")

                normalized_scroll_anchor = {
                    "anchorId": anchor_id,
                    "anchorBias": anchor_bias,
                    "intraOffset": intra_offset,
                    "beltPrev": normalized_prev,
                    "beltNext": normalized_next,
                    "anchorSortKey": {"domIndex": dom_index},
                }
            # Persist only the current tab contract; fields from older payloads are
            # intentionally accepted but omitted from the normalized snapshot.
            normalized[tab_id] = {
                "searchQuery": search_query,
                "scrollY": scroll_y,
                "anchorRootId": normalized_anchor_root_id,
                "scrollAnchor": normalized_scroll_anchor,
                "sortMode": normalized_sort_mode,
            }
        return normalized


tab_state_store = TabStateStore()
