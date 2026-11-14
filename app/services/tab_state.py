from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import re
from threading import Lock
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


class TabStateStore:
    """Server-owned tab state with namespace-scoped persistence in SQLite."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._encrypted_state_json: Optional[str] = None
        self._encrypted_state_nonce: Optional[bytes] = None
        self._encrypted_state_tag: Optional[bytes] = None
        self._tabs: Dict[str, Dict[str, object]] = {}
        self._reference_views: Dict[str, Dict[str, object]] = {}
        self._date_filters: Dict[str, Dict[str, str]] = {}
        self._file_filters: Dict[str, str] = {}
        # Whether the folder tree shows, for the view as its active tab is: switching search
        # contexts leaves it as it is (docs/ready-to-build/folders-tab-and-multiple-folders.md §1).
        self._tree_shown = False
        self._untagged_views: Set[str] = set()
        # The version at which each tab's scroll last started again at the top.
        self._scroll_restarted_at_version: Dict[str, int] = {}
        # The version at which Rename tag renamed each tab's search (rename_search_terms).
        self._search_renamed_at_version: Dict[str, int] = {}
        # Reference pages closed because their notes were deleted: a browser's save made before
        # it heard so may still name them, and is taken without them (update).
        self._closed_page_tab_ids: Set[str] = set()
        # The version at which pages last closed so: each view of the list carries it, and the
        # browser takes the server's tabs again when it has risen (adoptClosedReferencePages).
        self._pages_closed_at_version = 0
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
                snapshot = self._deserialize_snapshot_json(state_json)
                self._apply_snapshot_locked(snapshot)
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

    def snapshot(self) -> Dict[str, object]:
        with self._lock:
            self._try_decrypt_locked(token="", require_success=False)
            return self._snapshot_locked()

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

    def create_tab(self, *, copy_from_tab_id: str, copies_view: bool) -> Dict[str, object]:
        """A new tab after copy_from_tab_id. A duplicate (copies_view) copies everything that
        decides which notes the tab shows and their order; a new tab starts with nothing
        (the maintainer, 2026-11-02, docs/ui/state-handling.md)."""
        if not isinstance(copies_view, bool):
            raise TypeError("copies_view must be a bool")
        if not isinstance(copy_from_tab_id, str) or not copy_from_tab_id:
            raise InputRejected("copyFromTabId must be a non-empty string")
        if not _is_uuid_string(copy_from_tab_id):
            raise InputRejected("copyFromTabId must be a UUID string")

        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            if copy_from_tab_id not in self._tabs:
                raise InputRejected("copyFromTabId must reference an existing tab")
            if len(self._tabs) >= _MAX_TABS:
                raise InputRejected(f"max tabs reached ({_MAX_TABS})")

            new_tab_id = self._new_tab_id()
            while new_tab_id in self._tabs:
                new_tab_id = self._new_tab_id()

            if copies_view:
                self._tabs[new_tab_id] = deepcopy(self._tabs[copy_from_tab_id])
                if copy_from_tab_id in self._date_filters:
                    self._date_filters[new_tab_id] = deepcopy(self._date_filters[copy_from_tab_id])
                if copy_from_tab_id in self._file_filters:
                    self._file_filters[new_tab_id] = self._file_filters[copy_from_tab_id]
                if copy_from_tab_id in self._untagged_views:
                    self._untagged_views.add(new_tab_id)
            else:
                self._tabs[new_tab_id] = _blank_tab_entry()
            self._tab_order.append(new_tab_id)
            self._version += 1
            self._persist_locked(connection=None, encryption_service=None, force_plaintext=False)
            snapshot = self._snapshot_locked()
            snapshot["newTabId"] = new_tab_id
            return snapshot

    def delete_tab(self, *, tab_id: str) -> Dict[str, object]:
        if not isinstance(tab_id, str) or not tab_id:
            raise InputRejected("tabId must be a non-empty string")
        if not _is_uuid_string(tab_id):
            raise InputRejected("tabId must be a UUID string")

        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            if tab_id not in self._tabs:
                raise InputRejected("tabId must reference an existing tab")
            if len(self._tabs) <= 1:
                raise InputRejected("cannot delete the last remaining tab")

            was_active = tab_id == self._active_tab_id
            order = list(self._tab_order)
            idx = order.index(tab_id)
            order.pop(idx)
            del self._tabs[tab_id]

            if was_active:
                if idx < len(order):
                    next_active = order[idx]
                else:
                    next_active = order[idx - 1]
                self._active_tab_id = next_active

            self._tab_order = order
            self._reference_views = _normalize_reference_views(
                self._reference_views, self._tabs, from_storage=False,
            )
            self._forget_tab_settings_locked(tab_id)
            self._version += 1
            self._persist_locked(connection=None, encryption_service=None, force_plaintext=False)
            return self._snapshot_locked()

    def _forget_tab_settings_locked(self, tab_id: str) -> None:
        """What is kept beside a tab that is gone."""
        if tab_id in self._date_filters:
            del self._date_filters[tab_id]
        if tab_id in self._file_filters:
            del self._file_filters[tab_id]
        self._untagged_views.discard(tab_id)
        if tab_id in self._scroll_restarted_at_version:
            del self._scroll_restarted_at_version[tab_id]
        if tab_id in self._search_renamed_at_version:
            del self._search_renamed_at_version[tab_id]

    def close_pages_whose_notes_are_gone(self, *, note_exists: Callable[[str], bool]) -> bool:
        """Close each reference page none of whose notes exist any more, with the pages opened
        from it: its search context goes back to its search (`foo > bar`, bar deleted, reads `foo`;
        the maintainer, 2026-11-14). Shown on one of them: the search it was opened from. Returns
        whether any closed."""
        if not callable(note_exists):
            raise TypeError("note_exists must be callable")
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            closing = {
                tab_id for tab_id, view in self._reference_views.items()
                if not any(note_exists(note_id) for note_id in _reference_note_ids(view))
            }
            if not closing:
                return False
            is_growing = True
            while is_growing:
                opened_from_closing = {
                    tab_id for tab_id, view in self._reference_views.items()
                    if tab_id not in closing and view["fromTabId"] in closing
                }
                closing |= opened_from_closing
                is_growing = len(opened_from_closing) > 0
            if self._active_tab_id in closing:
                self._active_tab_id = self._search_shown_after_closing_locked(self._active_tab_id, closing)
            self._tab_order = [tab_id for tab_id in self._tab_order if tab_id not in closing]
            for tab_id in closing:
                del self._tabs[tab_id]
                del self._reference_views[tab_id]
                self._forget_tab_settings_locked(tab_id)
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

    def _search_shown_after_closing_locked(self, page_tab_id: str, closing: Set[str]) -> str:
        """The search a closed page was opened from; that context's first other tab when the
        search is gone as well."""
        origin_tab_id = _origin_tab_id(self._reference_views[page_tab_id])
        if origin_tab_id in self._tabs and origin_tab_id not in closing:
            return origin_tab_id
        remaining = [tab_id for tab_id in self._tab_order if tab_id not in closing]
        assert remaining, "closing pages leaves the search contexts they were opened from"
        return remaining[0]

    def update(
        self,
        *,
        active_tab_id: str,
        tabs: Dict[str, Dict[str, object]],
        tab_order: List[str],
        reference_views: object,
        read_at_version: int,
    ) -> Dict[str, object]:
        """Save the browser's snapshot of its tabs, read when the browser's state was
        at read_at_version (the last version it received)."""
        if not isinstance(read_at_version, int) or read_at_version < 0:
            raise InputRejected("version must be a non-negative integer")
        normalized_tabs = self._normalize_tabs(tabs, from_storage=False)
        normalized_order = self._normalize_tab_order(tab_order, normalized_tabs)
        normalized_reference_views = _normalize_reference_views(
            reference_views, normalized_tabs, from_storage=False,
        )
        if active_tab_id not in normalized_tabs:
            raise InputRejected("activeTabId must reference an existing tab")
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            existing_ids = set(self._tabs.keys())
            incoming_ids = set(normalized_tabs.keys())
            # Saved before the browser heard that pages closed with their notes: taken without them.
            closed_meanwhile = incoming_ids & self._closed_page_tab_ids
            if closed_meanwhile:
                normalized_tabs = {tab_id: entry for tab_id, entry in normalized_tabs.items() if tab_id not in closed_meanwhile}
                normalized_order = [tab_id for tab_id in normalized_order if tab_id not in closed_meanwhile]
                normalized_reference_views = _normalize_reference_views(
                    normalized_reference_views, normalized_tabs, from_storage=False,
                )
                incoming_ids -= closed_meanwhile
                if active_tab_id in closed_meanwhile:
                    active_tab_id = self._active_tab_id
            if incoming_ids != existing_ids:
                raise InputRejected("tab ids mismatch; use tab-state new/delete endpoints")
            normalized_tabs = {
                tab_id: self._tab_from_snapshot_locked(tab_id, entry, read_at_version)
                for tab_id, entry in normalized_tabs.items()
            }
            # Scroll persistence posts about once a second; unchanged state must
            # not re-encrypt and rewrite the row. Clients accept the same version.
            if (
                self._tabs == normalized_tabs
                and self._active_tab_id == active_tab_id
                and self._tab_order == normalized_order
                and self._reference_views == normalized_reference_views
            ):
                return self._snapshot_locked()
            self._tabs = normalized_tabs
            self._active_tab_id = active_tab_id
            self._tab_order = normalized_order
            self._reference_views = normalized_reference_views
            self._version += 1
            self._persist_locked(connection=None, encryption_service=None, force_plaintext=False)
            return self._snapshot_locked()

    def _tab_from_snapshot_locked(
        self, tab_id: str, entry: Dict[str, object], read_at_version: int,
    ) -> Dict[str, object]:
        """A tab as the browser's snapshot has it, less what the snapshot cannot know.
        A snapshot (a scroll or search save) can be read before a sort order or filter
        changes and reach the server after it. Only set_sort_mode sets the sort order,
        and a scroll read before the tab's scroll restarted belongs to the old view."""
        current = self._tabs[tab_id]
        merged = {**entry, "sortMode": current["sortMode"]}
        if (
            tab_id in self._scroll_restarted_at_version
            and read_at_version < self._scroll_restarted_at_version[tab_id]
        ):
            for key in _TAB_SCROLL_KEYS:
                merged[key] = current[key]
        # A search Rename tag renamed after the snapshot was read keeps its new name.
        if tab_id in self._search_renamed_at_version and read_at_version < self._search_renamed_at_version[tab_id]:
            merged["searchQuery"] = current["searchQuery"]
        assert merged.keys() == entry.keys(), "a snapshot tab keeps its own keys"
        return merged

    def get_sort_mode(self, *, tab_id: Optional[str]) -> str:
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            if tab_id is None:
                target_tab_id = self._active_tab_id
            else:
                target_tab_id = tab_id
            if target_tab_id not in self._tabs:
                raise InputRejected("tab_id must reference an existing tab")
            value = self._tabs[target_tab_id]["sortMode"]
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

    def set_file_filter(self, *, tab_id: str, file_filter: str | None) -> Dict[str, object]:
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
            snapshot = self._snapshot_locked()
            snapshot["changed"] = changed
            return snapshot

    def set_tree_shown(self, *, is_shown: bool) -> Dict[str, object]:
        """The folders tab: the tree shown or hidden, nothing else (no search context changes;
        folders-tab-and-multiple-folders.md §1)."""
        if not isinstance(is_shown, bool):
            raise InputRejected("isShown must be true or false")
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            if self._tree_shown != is_shown:
                self._tree_shown = is_shown
                self._version += 1
                self._persist_locked(connection=None, encryption_service=None, force_plaintext=False)
            return self._snapshot_locked()

    def choose_folder(self, *, tab_id: str, folder: str, adds: bool) -> Dict[str, object]:
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
            return self._snapshot_locked()

    def set_untagged_view(self, *, tab_id: str, is_untagged_view: bool) -> Dict[str, object]:
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
            snapshot = self._snapshot_locked()
            snapshot["changed"] = changed
            return snapshot

    def _restart_tab_scroll_locked(self, tab_id: str) -> None:
        entry = self._tabs[tab_id]
        entry["scrollY"] = 0
        entry["scrollAnchor"] = None
        entry["anchorRootId"] = None
        self._version += 1
        self._scroll_restarted_at_version[tab_id] = self._version
        self._persist_locked(connection=None, encryption_service=None, force_plaintext=False)

    def set_date_filter(self, *, tab_id: str, date_filter: RootDateFilter | None) -> Dict[str, object]:
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
            snapshot = self._snapshot_locked()
            snapshot["changed"] = changed
            return snapshot

    def get_active_tab_id(self) -> str:
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            if self._active_tab_id not in self._tabs:
                raise RuntimeError("Active tab id is missing from tab state")
            return self._active_tab_id

    def search_context_with_search(self, *, search: str) -> str:
        """The search context, in list order, whose search has the same terms as this one, or ""
        for none: what a search link opens (docs/ready-to-build/search-links.md §3). Folder contexts
        are search contexts too (folder-tags-in-search.md §5); reference views are never a search link's,
        nor is a context on a reference page: it shows the page, not its search, and stays there while
        the link opens the search in a new context (the maintainer, 2026-11-14)."""
        if not isinstance(search, str) or search.strip() == "":
            raise InputRejected("A search link needs a search.")
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            on_a_page = {_origin_tab_id(view) for view in self._reference_views.values()}
            for tab_id in self._tab_order:
                if tab_id in self._reference_views or tab_id in on_a_page:
                    continue
                tab_search = self._tabs[tab_id]["searchQuery"]
                if not isinstance(tab_search, str):
                    raise RuntimeError("Tab searchQuery must be a string")
                if same_search(tab_search, search):
                    return tab_id
            return ""

    def get_search_query(self, *, tab_id: Optional[str]) -> str:
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            if tab_id is None:
                target_tab_id = self._active_tab_id
            else:
                target_tab_id = tab_id
            if target_tab_id not in self._tabs:
                raise InputRejected("tab_id must reference an existing tab")
            value = self._tabs[target_tab_id]["searchQuery"]
            if not isinstance(value, str):
                raise RuntimeError("Tab searchQuery must be a string")
            return value

    def set_sort_mode(self, *, tab_id: str, sort_mode: str) -> Dict[str, object]:
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

            snapshot = self._snapshot_locked()
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
        self._active_tab_id = default_tab_id
        self._tabs = {default_tab_id: _blank_tab_entry()}
        self._tab_order = [default_tab_id]
        self._reference_views = {}
        self._date_filters = {}
        self._file_filters = {}
        self._tree_shown = False
        self._untagged_views = set()
        self._scroll_restarted_at_version = {}
        self._search_renamed_at_version = {}
        self._closed_page_tab_ids = set()
        self._version = version

    def _snapshot_locked(self) -> Dict[str, object]:
        return {
            "activeTabId": self._active_tab_id,
            "tabs": deepcopy(self._tabs),
            "tabOrder": list(self._tab_order),
            "referenceViews": deepcopy(self._reference_views),
            "dateFilters": deepcopy(self._date_filters),
            "fileFilters": dict(self._file_filters),
            "treeShown": self._tree_shown,
            "untaggedViews": sorted(self._untagged_views),
            "version": self._version,
        }

    def _serialize_snapshot_locked(self) -> str:
        return json.dumps(self._snapshot_locked(), separators=(",", ":"), sort_keys=True)

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

    def _apply_snapshot_locked(self, snapshot: Dict[str, object]) -> None:
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
        self._tabs = normalized_tabs
        self._tab_order = normalized_order
        self._reference_views = _normalize_reference_views(
            snapshot["referenceViews"], normalized_tabs, from_storage=True,
        )
        self._date_filters = _normalize_date_filters(
            snapshot["dateFilters"], normalized_tabs,
        )
        self._file_filters = _normalize_file_filters(snapshot["fileFilters"], normalized_tabs)
        # Folder contexts were a kind of search context until 2026-11-11: each becomes an ordinary
        # one with the same search (folders-tab-and-multiple-folders.md §1), once, as the stored
        # state no longer names them once saved.
        folder_contexts = _normalize_folder_contexts(snapshot["folderContexts"], normalized_tabs)
        tree_shown = snapshot["treeShown"]
        assert isinstance(tree_shown, bool), "read as a bool from storage"
        self._tree_shown = tree_shown
        # A folder kept apart from the search (before 2026-11-11) goes in front of its folder
        # context's search, once (folder-tags-in-search.md §2). One saved on a plain search
        # (before 2026-11-07) is dropped.
        for tab_id, folder in _normalize_folder_filters(snapshot["folderFilters"], normalized_tabs).items():
            if tab_id in folder_contexts:
                search = self._tabs[tab_id]["searchQuery"]
                assert isinstance(search, str), "a tab's search is text"
                self._tabs[tab_id]["searchQuery"] = f"{folder} {search}".strip()
        self._untagged_views = _normalize_untagged_views(snapshot["untaggedViews"], normalized_tabs)
        self._scroll_restarted_at_version = {}
        self._search_renamed_at_version = {}
        self._active_tab_id = active_tab_id
        self._version = version

    def _try_decrypt_locked(self, *, token: str, require_success: bool) -> None:
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
        snapshot = self._deserialize_snapshot_json(plaintext)
        self._apply_snapshot_locked(snapshot)
        self._clear_encrypted_state_locked()

    def rename_search_terms(self, *, rename: Callable[[str], str], connection) -> int:
        """Each search context's search, and a reference view's queries, as `rename` returns
        them (meta_tag_renames.py, a one-time pass; Rename tag, rename_tag.py), saved with
        `connection` when any changed. Returns how many searches changed."""
        if not callable(rename):
            raise TypeError("rename must be callable")
        with self._lock:
            self._try_decrypt_locked(token="", require_success=True)
            changed = 0
            renamed_tab_ids: List[str] = []
            for tab_id, tab in self._tabs.items():
                search_query = tab["searchQuery"]
                assert isinstance(search_query, str), "a tab's search is text"
                renamed = rename(search_query)
                if renamed != search_query:
                    tab["searchQuery"] = renamed
                    renamed_tab_ids.append(tab_id)
                    changed += 1
            for view in self._reference_views.values():
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
            for tab_id in renamed_tab_ids:
                self._search_renamed_at_version[tab_id] = self._version
            self._persist_locked(connection=connection, encryption_service=None, force_plaintext=False)
            return changed

    def _persist_locked(
        self,
        *,
        connection,
        encryption_service: object | None,
        force_plaintext: bool,
    ) -> None:
        if not isinstance(force_plaintext, bool):
            raise TypeError("force_plaintext must be a bool")
        snapshot_json = self._serialize_snapshot_locked()
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
