from __future__ import annotations

from app.services.resource_limits import SENSITIVE_MEMO_BYTES
from threading import RLock

from datetime import datetime
from typing import Dict, List, Optional

from app.services.file_kinds import FILE_FILTER_ANY
from app.services.file_registry import file_registry
from app.services.note_store import store as note_store
from app.utils.text_utils import strip_html
from app.security.sensitive_cache import sensitive_lru_cache


SORT_MODE_NORMAL = "normal"
SORT_MODE_CREATED = "created"
SORT_MODE_UPDATED = "updated"
SORT_MODE_ALPHABETICAL = "alphabetical"
SORT_MODE_CONTENT_VOLUME = "content-volume"
# Offered only with a Files filter on (docs/ui/command-palette.md, Sort Order).
SORT_MODE_FILE_SIZE = "file-size"
BASE_SORT_MODES = frozenset(
    {
        SORT_MODE_NORMAL,
        SORT_MODE_CREATED,
        SORT_MODE_UPDATED,
        SORT_MODE_ALPHABETICAL,
        SORT_MODE_CONTENT_VOLUME,
        SORT_MODE_FILE_SIZE,
    }
)
# Reverse Order: any order, the manual one too, read bottom to top ("alphabetical-reversed"
# is Z to A). An older MetaList reads a mode it does not know as normal.
SORT_MODE_REVERSED_SUFFIX = "-reversed"
SORT_MODES = BASE_SORT_MODES | frozenset(mode + SORT_MODE_REVERSED_SUFFIX for mode in BASE_SORT_MODES)
TIMESTAMP_SORT_MODES = frozenset({SORT_MODE_CREATED, SORT_MODE_UPDATED})
# An index not yet built for any store revision.
_NO_REVISION = -1
_ALPHABETICAL_KEY_MEMO_ENTRIES = 32768
# The missing-parents error names at most this many of them.
_MISSING_PARENTS_SHOWN = 5


def normalize_sort_mode(sort_mode: object) -> str:
    if not isinstance(sort_mode, str):
        raise TypeError(f"sort_mode must be a string, got {type(sort_mode)}")
    normalized = sort_mode.strip().lower()
    if normalized not in SORT_MODES:
        raise ValueError(f"Unsupported sort mode: {sort_mode!r}")
    return normalized


def is_sort_mode_reversed(sort_mode: object) -> bool:
    return normalize_sort_mode(sort_mode).endswith(SORT_MODE_REVERSED_SUFFIX)


def base_sort_mode(sort_mode: object) -> str:
    """The order a mode sorts by, without its direction."""
    normalized = normalize_sort_mode(sort_mode)
    if is_sort_mode_reversed(normalized):
        base = normalized.removesuffix(SORT_MODE_REVERSED_SUFFIX)
        assert base in BASE_SORT_MODES
        return base
    return normalized


def is_root_reorder_locked(sort_mode: object) -> bool:
    return normalize_sort_mode(sort_mode) != SORT_MODE_NORMAL


def _get_note_timestamp(note_id: str, sort_mode: str) -> datetime:
    record = note_store.get_note(note_id)
    if sort_mode == SORT_MODE_CREATED:
        timestamp = record.created_at
        field_name = "created_at"
    elif sort_mode == SORT_MODE_UPDATED:
        timestamp = record.updated_at
        field_name = "updated_at"
    else:
        raise ValueError(f"Timestamp lookup unsupported for sort mode {sort_mode!r}")

    if not isinstance(timestamp, datetime):
        raise RuntimeError(
            f"Root note {note_id} is missing required {field_name} for sort mode {sort_mode}"
        )
    return timestamp


_metric_lock = RLock()


class _RootMetrics:
    """Per-root subtree aggregates ('updated' max, 'volume' sum) at one store revision.

    Note records are immutable, so comparing the new snapshot with the previous
    one by identity finds exactly the notes an edit touched; only the roots
    above them (before and after the edit) are re-aggregated.
    """

    def __init__(self, store, records, *, include_text):
        self.store = store
        self.include_text = include_text
        self.records = {}
        self.children = {None: set()}
        self.own = {}
        self.text_keys = {}
        self.roots = {}
        self.revision = _NO_REVISION
        for note_id, record in records.items():
            if note_id not in self.children:
                self.children[note_id] = set()
            if record.parent_id not in self.children:
                self.children[record.parent_id] = set()
            self.children[record.parent_id].add(note_id)
            self.own[note_id] = self._own_values(note_id, record)
        missing_parents = set(self.children) - set(records) - {None}
        if missing_parents:
            raise RuntimeError(f'Root sorting parents are missing: {sorted(missing_parents)[:_MISSING_PARENTS_SHOWN]}')
        reached = 0
        for root_id in self.children[None]:
            self.roots[root_id], size = self._aggregate(root_id)
            reached += size
        # Notes no root reaches sit on disconnected cycles.
        if reached != len(records):
            raise RuntimeError('Disconnected cycle in root sorting hierarchy')
        self.records = records

    def _own_values(self, note_id, record):
        volume = 0
        if self.include_text:
            if note_id in self.text_keys and self.text_keys[note_id][0] is record.content:
                volume = self.text_keys[note_id][1]
            else:
                volume = len(strip_html(record.content))
                self.text_keys[note_id] = (record.content, volume)
        return record.updated_at, volume

    @staticmethod
    def _root_of(records, note_id):
        steps = 0
        while records[note_id].parent_id is not None:
            parent_id = records[note_id].parent_id
            if parent_id not in records:
                raise RuntimeError(f'Root sorting parent {parent_id} of {note_id} is missing')
            note_id = parent_id
            steps += 1
            if steps > len(records):
                raise RuntimeError('Cycle in root sorting hierarchy')
        return note_id

    def _aggregate(self, root_id):
        updated, volume = self.own[root_id]
        pending = [root_id]
        visited = {root_id}
        while pending:
            for child in self.children[pending.pop()]:
                if child in visited:
                    raise RuntimeError('Cycle in root sorting hierarchy')
                visited.add(child)
                pending.append(child)
                child_updated, child_volume = self.own[child]
                volume += child_volume
                if not isinstance(updated, datetime) or not isinstance(child_updated, datetime):
                    updated = None
                elif child_updated > updated:
                    updated = child_updated
        return {'updated': updated, 'volume': volume}, len(visited)

    def apply(self, records):
        previous = self.records
        changed = [note_id for note_id, record in records.items()
                   if note_id not in previous or previous[note_id] is not record]
        removed = [note_id for note_id in previous if note_id not in records]
        dirty_roots = set()
        for note_id in (*changed, *removed):
            if note_id in previous:
                dirty_roots.add(self._root_of(previous, note_id))
                self.children[previous[note_id].parent_id].discard(note_id)
        for note_id in removed:
            del self.own[note_id]
            del self.children[note_id]
            if note_id in self.text_keys:
                del self.text_keys[note_id]
        for note_id in changed:
            if note_id not in self.children:
                self.children[note_id] = set()
        for note_id in changed:
            record = records[note_id]
            # Any new cycle passes through a changed note, so this finds it.
            dirty_roots.add(self._root_of(records, note_id))
            if record.parent_id not in self.children:
                raise RuntimeError(f'Root sorting parent {record.parent_id} of {note_id} is missing')
            self.children[record.parent_id].add(note_id)
            self.own[note_id] = self._own_values(note_id, record)
        for root_id in dirty_roots:
            if root_id in records and records[root_id].parent_id is None:
                self.roots[root_id], _ = self._aggregate(root_id)
            elif root_id in self.roots:
                del self.roots[root_id]
        self.records = records
        assert len(self.roots) == len(self.children[None])


_metric_state = None  # shockharness: ignore[STATE001] reason="every access holds _metric_lock"


def _metrics(*, include_text):
    global _metric_state
    with _metric_lock:
        revision = note_store.revision
        state = _metric_state
        if state is not None and state.store is note_store and (state.include_text or not include_text):
            if state.revision != revision:
                state.apply(note_store.snapshot())
                state.revision = revision
            return state.roots
        state = _RootMetrics(note_store, note_store.snapshot(), include_text=include_text)
        state.revision = revision
        _metric_state = state
        return state.roots


def clear_root_sort_cache() -> None:
    global _metric_state
    with _metric_lock:
        _metric_state = None
        _alphabetical_key.cache_clear()


def _get_root_subtree_updated_timestamp(root_id: str):
    value = _metrics(include_text=False)[root_id]['updated']
    if not isinstance(value, datetime):
        raise RuntimeError('Root subtree is missing valid timestamps')
    return value


@sensitive_lru_cache(maxsize=_ALPHABETICAL_KEY_MEMO_ENTRIES, max_bytes=SENSITIVE_MEMO_BYTES)
def _alphabetical_key(content: str):
    text = strip_html(content).strip()
    return text.casefold(), text, len(text)


def _get_root_content_sort_key(note_id: str):
    return _alphabetical_key(note_store.get_note(note_id).content)


def _get_root_subtree_content_volume(root_id: str) -> int:
    return _metrics(include_text=True)[root_id]['volume']


def get_root_sort_timestamps(sort_mode: object) -> Dict[str, datetime]:
    normalized = base_sort_mode(sort_mode)
    canonical_root_ids = note_store.get_children(None)
    if normalized not in TIMESTAMP_SORT_MODES:
        return {}

    root_timestamps: Dict[str, datetime] = {}
    for root_id in canonical_root_ids:
        if normalized == SORT_MODE_CREATED:
            root_timestamps[root_id] = _get_note_timestamp(root_id, normalized)
        else:
            root_timestamps[root_id] = _get_root_subtree_updated_timestamp(root_id)
    return root_timestamps


def _alphabetical_sort_key(item: tuple[str, object, int]) -> tuple[object, int]:
    _root_id, content_key, canonical_index = item
    return content_key, canonical_index


def _content_volume_sort_key(item: tuple[str, int, int]) -> tuple[int, int]:
    _root_id, character_count, canonical_index = item
    return -character_count, canonical_index


def _root_id_of(note_id: str) -> str:
    current = note_store.get_note(note_id)
    while current.parent_id is not None:
        current = note_store.get_note(current.parent_id)
    return current.id


def _sizes_and_root_files(file_filter: str | None) -> tuple[Dict[str, int], Dict[str, set[str]]]:
    """The size of each file the Files filter keeps, and which of them each root that has
    any holds in its subtree, so a file counts once however often the root uses it.
    Without a filter (the AI checking a search alone) every file counts."""
    kind = FILE_FILTER_ANY
    if file_filter is not None:
        kind = file_filter
    sizes = file_registry.sizes_of_kind(kind)
    files_by_root: Dict[str, set[str]] = {}
    for file_id in sizes:
        for root_id in {_root_id_of(note_id) for note_id in note_store.note_ids_referencing({file_id})}:
            if root_id not in files_by_root:
                files_by_root[root_id] = set()
            files_by_root[root_id].add(file_id)
    return sizes, files_by_root


def _total_size(sizes: Dict[str, int], file_ids: set[str]) -> int:
    return sum(sizes[file_id] for file_id in file_ids)


def _root_file_totals(file_filter: str | None) -> Dict[str, int]:
    sizes, files_by_root = _sizes_and_root_files(file_filter)
    return {root_id: _total_size(sizes, file_ids) for root_id, file_ids in files_by_root.items()}


def _newest_first_sort_key(item: tuple[str, datetime, int]) -> tuple[float, int]:
    _root_id, timestamp, canonical_index = item
    return -timestamp.timestamp(), canonical_index


def get_root_ids_for_sort_mode(
    sort_mode: object,
    *,
    root_timestamps: Dict[str, datetime],
    file_filter: str | None,
) -> List[str]:
    ordered = _root_ids_in_base_order(base_sort_mode(sort_mode), root_timestamps=root_timestamps, file_filter=file_filter)
    if is_sort_mode_reversed(sort_mode):
        return ordered[::-1]
    return ordered


def _root_ids_in_base_order(
    normalized: str,
    *,
    root_timestamps: Dict[str, datetime],
    file_filter: str | None,
) -> List[str]:
    canonical_root_ids = note_store.get_children(None)
    if normalized == SORT_MODE_NORMAL:
        return canonical_root_ids
    if normalized == SORT_MODE_ALPHABETICAL:
        decorated_alpha = []
        for canonical_index, root_id in enumerate(canonical_root_ids):
            content_key = _get_root_content_sort_key(root_id)
            decorated_alpha.append((root_id, content_key, canonical_index))
        decorated_alpha.sort(key=_alphabetical_sort_key)
        return [root_id for root_id, _, _ in decorated_alpha]
    if normalized == SORT_MODE_CONTENT_VOLUME:
        decorated_volume = []
        for canonical_index, root_id in enumerate(canonical_root_ids):
            character_count = _get_root_subtree_content_volume(root_id)
            decorated_volume.append((root_id, character_count, canonical_index))
        decorated_volume.sort(key=_content_volume_sort_key)
        return [root_id for root_id, _, _ in decorated_volume]
    if normalized == SORT_MODE_FILE_SIZE:
        totals = _root_file_totals(file_filter)
        return [
            root_id for _, root_id in sorted(
                enumerate(canonical_root_ids),
                key=lambda item: (-(totals[item[1]] if item[1] in totals else 0), item[0]),  # shockharness: ignore[DEF002] reason="a root with no file has no entry: its files total 0 bytes, which is the order's meaning"
            )
        ]

    decorated = []
    for canonical_index, root_id in enumerate(canonical_root_ids):
        if root_id not in root_timestamps:
            raise RuntimeError(f"Missing root sort timestamp for {root_id}")
        timestamp = root_timestamps[root_id]
        decorated.append((root_id, timestamp, canonical_index))

    decorated.sort(key=_newest_first_sort_key)
    return [root_id for root_id, _, _ in decorated]


def build_file_size_labels(root_ids: List[str], sort_mode: object, *, file_filter: str | None) -> Dict[str, Dict[str, int]]:
    """In the File size order, what the browser shows beside the listed roots: each root's
    total and the size of each file it counts. Nothing in any other order."""
    labels: Dict[str, Dict[str, int]] = {"rootTotals": {}, "files": {}}
    if base_sort_mode(sort_mode) != SORT_MODE_FILE_SIZE:
        return labels
    sizes, files_by_root = _sizes_and_root_files(file_filter)
    for root_id in root_ids:
        if root_id in files_by_root:
            file_ids = files_by_root[root_id]
            labels["rootTotals"][root_id] = _total_size(sizes, file_ids)
            labels["files"].update({file_id: sizes[file_id] for file_id in file_ids})
    return labels


def build_root_sort_buckets(
    root_ids: List[str],
    sort_mode: object,
    *,
    root_timestamps: Dict[str, datetime],
) -> Dict[str, Dict[str, str]]:
    normalized = base_sort_mode(sort_mode)
    if normalized not in TIMESTAMP_SORT_MODES:
        return {}

    buckets: Dict[str, Dict[str, str]] = {}
    for root_id in root_ids:
        if root_id not in root_timestamps:
            raise RuntimeError(f"Missing root sort timestamp for {root_id}")
        timestamp = root_timestamps[root_id].astimezone()
        buckets[root_id] = {
            "key": timestamp.strftime("%Y-%m-%d"),
            "label": timestamp.strftime("%Y/%m/%d - %A"),
        }
    return buckets
