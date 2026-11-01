"""Virtual folders, an experiment (docs/ready-to-build/virtual-folders.md): a tag ending in
`/` is a folder (`Projects/Client-A/`), shown as a tree of folders beside the notes column
(only folders: the maintainer, 2026-11-01: a folder's notes show in the column).

Nothing of it is stored (the maintainer, 2026-11-01: the experiment may be dropped in a few
hours, so it must not change the database): each tab's folder filter lives in this
process's memory, as long as the server runs, and whether the tree shows in the browser
(virtual-folders-state.js). A folder filter narrows a view to the notes in that folder and
the folders below it, by repeating every clause of the view's search once per folder tag
(`Projects/`, `Projects/Client-A/`, …); the notes under a filed note inherit its tag, so
they come with it."""

from __future__ import annotations

from dataclasses import replace
from threading import Lock
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from app.services.input_errors import InputRejected
from app.services.note_store import store as note_store
from app.services.search_index import search_index
from app.services.search_query import SearchClause, format_search_query, parse_search_query
from app.services.snapshot import (
    clause_excluded_note_ids,
    clause_has_positive_terms,
    is_plain_clause,
    resolve_search_scope,
)
from app.services.tag_ontology import _is_valid_tag_token

FOLDER_MARK = "/"
# A tab with no folder filter.
NO_FOLDER = ""


class VirtualFolderState:
    """Each tab's folder filter: this process's memory only."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._filters: Dict[str, str] = {}

    def filter_of(self, tab_id: str) -> str:
        """The tab's folder, '' for none."""
        with self._lock:
            if tab_id not in self._filters:
                return NO_FOLDER
            return self._filters[tab_id]

    def set_filter(self, tab_id: str, folder: str) -> None:
        if not isinstance(tab_id, str) or tab_id == "":
            raise ValueError("set_filter requires a tab id")
        if folder != NO_FOLDER and not is_folder_tag(folder):
            raise InputRejected(f"{folder} is not a folder")
        with self._lock:
            if folder != NO_FOLDER:
                self._filters[tab_id] = folder
            elif tab_id in self._filters:
                del self._filters[tab_id]

    def move_filters(self, folder: str, new_path: str) -> None:
        """A renamed or moved folder: a tab filtered to it, or below it, follows it."""
        with self._lock:
            for tab_id, filtered in list(self._filters.items()):
                if filtered.casefold().startswith(folder.casefold()):
                    self._filters[tab_id] = new_path + filtered[len(folder):]

    def drop_filters_under(self, folder: str) -> None:
        """A deleted folder: a tab filtered to it, or below it, shows every folder again."""
        with self._lock:
            for tab_id, filtered in list(self._filters.items()):
                if filtered.casefold().startswith(folder.casefold()):
                    del self._filters[tab_id]


virtual_folder_state = VirtualFolderState()


def is_folder_tag(tag: str) -> bool:
    """A tag ending in `/` is a folder; `a/b` stays an ordinary tag."""
    return tag.endswith(FOLDER_MARK) and _is_valid_tag_token(tag)


def search_in_folder(search: str, folder: str) -> str:
    """The view's search ('' for none) narrowed to folder and the folders below it (the
    maintainer, 2026-11-01: Projects/ shows Client-A's and Client-B's notes too), '' for no
    filter. Each clause of the search is kept once per folder tag (OR between them)."""
    if folder == NO_FOLDER:
        return search
    assert is_folder_tag(folder), folder
    parsed = parse_search_query(search)
    # The folder itself comes first even when no note carries it yet (just made): it narrows to nothing.
    tags = [folder] + [
        tag for tag in all_folder_tags()
        if tag.casefold().startswith(folder.casefold()) and tag.casefold() != folder.casefold()
    ]
    clauses = tuple(
        replace(clause, required_tags=clause.required_tags | {tag}) for clause in parsed.clauses for tag in tags
    )
    return format_search_query(replace(parsed, clauses=clauses))


def search_for_new_note(search: Optional[str], folder: str) -> Optional[str]:
    """The search a note made in the view takes its tags from (None for no search): in a
    folder, each clause also requires the folder itself (not the folders below it), so the
    note is filed in the folder chosen and shows in its view."""
    if folder == NO_FOLDER:
        return search
    assert is_folder_tag(folder), folder
    if search is None:
        return folder
    parsed = parse_search_query(search)
    clauses = tuple(replace(clause, required_tags=clause.required_tags | {folder}) for clause in parsed.clauses)
    return format_search_query(replace(parsed, clauses=clauses))


def all_folder_tags() -> List[str]:
    """Every folder tag some note carries, A to Z. Read from the search index's count of
    written tags, kept up to date as notes change: no note is read (walking every note on
    each change made a save into a new folder slow)."""
    found: Dict[str, str] = {}
    for tag in search_index.list_explicit_tag_frequencies():
        if is_folder_tag(tag) and tag.casefold() not in found:
            found[tag.casefold()] = tag
    return [found[key] for key in sorted(found)]


def folder_paths() -> List[str]:
    """Every folder in the tree: each folder tag and the folders above it (Projects/ for
    Projects/Client-A/), A to Z."""
    paths: Dict[str, str] = {}
    for tag in all_folder_tags():
        parts = tag.rstrip(FOLDER_MARK).split(FOLDER_MARK)
        for depth in range(len(parts)):
            path = FOLDER_MARK.join(parts[: depth + 1]) + FOLDER_MARK
            if path.casefold() not in paths:
                paths[path.casefold()] = path
    return [paths[key] for key in sorted(paths)]


# The counts for the last view asked about, until the notes change.
_counts_cache_lock = Lock()
_counts_cache: Dict[str, object] = {"key": None, "counts": {}}


def folder_note_counts(search: str) -> Dict[str, int]:
    """How many notes each folder shows, with the folders below it, in a view searching for
    search ('' for none): the count clicking it shows (the maintainer, 2026-11-01: the tags
    searched for narrow it). NO_FOLDER, the top, counts every note the view shows."""
    key: Tuple[int, int, str] = (note_store.revision, search_index.revision, search)
    with _counts_cache_lock:
        if _counts_cache["key"] != key:
            _counts_cache["counts"] = _count_notes_by_folder(search)
            _counts_cache["key"] = key
        return _counts_cache["counts"]


def _count_notes_by_folder(search: str) -> Dict[str, int]:
    root_ids = note_store.get_children(None)
    paths = folder_paths()
    counts = {NO_FOLDER: _count_roots(search, root_ids)}
    clauses = parse_search_query(search).clauses
    if all(is_plain_clause(clause) for clause in clauses):
        counts.update(_count_in_one_pass(clauses, paths))
        return counts
    # Stats, values, MAX/MIN or a note's id: each folder searched as clicking it would.
    for path in paths:
        counts[path] = _count_roots(search_in_folder(search, path), root_ids)
    return counts


def _count_in_one_pass(clauses: Tuple[SearchClause, ...], paths: List[str]) -> Dict[str, int]:
    """The counts search_in_folder's view would show, for every folder at once. A view
    narrowed to a folder shows a root when, for some clause, a note under the root (or the
    root) is found by the clause, carries one of the folder's tags, and the root itself is
    not excluded by the clause (snapshot.resolve_search_scope); with a plain clause, the
    notes it finds with a tag added are those it finds that carry the tag."""
    tags = all_folder_tags()
    notes_by_path: Dict[str, Set[str]] = {}
    holders_by_tag = {tag: search_index.query_clause_note_ids(_tag_clause(tag)) for tag in tags}
    for path in paths:
        notes: Set[str] = set()
        for tag in tags:
            if tag.casefold().startswith(path.casefold()):
                notes |= holders_by_tag[tag]
        notes_by_path[path] = notes
    root_by_note: Dict[str, str] = {}
    roots_by_path: Dict[str, Set[str]] = {path: set() for path in paths}
    every_note = frozenset(note_store.list_note_ids())
    for clause in clauses:
        found = _found_by(clause, every_note)
        excluded = clause_excluded_note_ids(clause)
        for path in paths:
            for note_id in notes_by_path[path] & found:
                root_id = _root_of(note_id, root_by_note)
                if root_id not in excluded:
                    roots_by_path[path].add(root_id)
    return {path: len(roots) for path, roots in roots_by_path.items()}


def _found_by(clause: SearchClause, every_note: FrozenSet[str]) -> FrozenSet[str]:
    if not clause_has_positive_terms(clause):
        return every_note
    return frozenset(search_index.query_clause_note_ids(clause))


def _tag_clause(tag: str) -> SearchClause:
    return SearchClause(
        required_tags=frozenset({tag}), forbidden_tags=frozenset(), required_text=(), forbidden_text=(),
        required_properties=(), forbidden_properties=(),
    )


def _root_of(note_id: str, root_by_note: Dict[str, str]) -> str:
    """The top-level note above note_id (itself at the top), remembered along the way."""
    path = [note_id]
    current = note_id
    while current not in root_by_note:
        parent_id = note_store.get_note(current).parent_id
        if parent_id is None:
            break
        path.append(parent_id)
        current = parent_id
    root_id = current
    if current in root_by_note:
        root_id = root_by_note[current]
    for visited in path:
        root_by_note[visited] = root_id
    return root_id


def _count_roots(search: str, root_ids: List[str]) -> int:
    scope = resolve_search_scope(
        search=search, editing_note_id=None, sort_mode="normal", date_filter=None, ordered_root_ids=root_ids,
    )
    if not scope.search_active:
        return len(root_ids)
    return scope.search_root_count_total
