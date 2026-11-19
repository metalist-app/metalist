"""The tab state under random orderings of requests from several views
(docs/future-plans/one-writer-refactoring.md, idea 2). Each view acts on the tabs it was last told
of, which another view may have changed since, so stale requests come up by themselves. After
every request the rules agreed 2026-11-18 are checked:

1. nothing a person could cause is an error: a request is answered or calmly refused;
2. a view's own change holds in its answer;
3. a request changes only what it names, in every view;
4. what a view is told matches what the server holds;
5. a change reaches every other view once, and a view's own change is no news to it;
6. the version only rises, and rises with every change a view can see;
7. the state is always well formed;
8. a restart loses nothing.

The unit run plays the same orderings every time. To play more, different each time:

    TAB_STATE_SIMULATION_EXAMPLES=5000 .venv/bin/python -m pytest tests/unit/test_tab_state_simulation.py

(about 40 seconds for each 1,000). A failing ordering is printed shrunk to the shortest one that
fails; keep it below as an ordinary test before fixing it."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Set, Tuple

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, precondition, rule, run_state_machine_as_test

from app.models.database import SafeSession
from app.security.encryption import set_encryption_required
from app.services.edit_locks import edit_locks
from app.services.input_errors import InputRejected
from app.services.tab_state import TabStateStore

MAC = "10000000-0000-4000-8000-0000000000f1"
PHONE = "10000000-0000-4000-8000-0000000000f2"
THIRD = "10000000-0000-4000-8000-0000000000f3"
VIEWS = (MAC, PHONE, THIRD)
NOTES = ("20000000-0000-4000-8000-0000000000f1", "20000000-0000-4000-8000-0000000000f2")
SEARCHES = ("", "groceries", "recipes", *NOTES)
SORT_MODES = ("normal", "created", "alphabetical")
FILE_FILTERS = (None, "image", "pdf")
SCROLLS = (0, 240, 480)
SCROLL_KEYS = ("scrollY", "anchorRootId", "scrollAnchor")
# What an answer carries beside the view's tabs.
ANSWER_ONLY_KEYS = ("newTabId", "changed", "searchContextsRevision")
EXAMPLES_IN_THE_UNIT_RUN = 200
STEPS_IN_THE_UNIT_RUN = 30
STEPS_IN_A_LONG_RUN = 50
LONG_RUN_EXAMPLES_VARIABLE = "TAB_STATE_SIMULATION_EXAMPLES"

Change = Tuple[str, ...]
Allowed = Callable[[str, Change], bool]


def _told(answer: Dict[str, object]) -> Dict[str, object]:
    """The view's tabs in an answer, without what belongs to the request."""
    return {key: value for key, value in answer.items() if key not in ANSWER_ONLY_KEYS}


def _entry(entries: Dict[str, object], tab_id: str) -> Tuple[object, ...]:
    """A tab's entry among entries, or the empty tuple when it has none."""
    if tab_id in entries:
        return (entries[tab_id],)
    return ()


def _tab_changes(before: Dict[str, object], after: Dict[str, object]) -> Set[Change]:
    """The tabs added, removed, reordered or changed between two readings of one view's tabs."""
    found: Set[Change] = set()
    old_tabs, new_tabs = before["tabs"], after["tabs"]
    for tab_id in set(old_tabs) - set(new_tabs):
        found.add(("removed", tab_id))
    for tab_id in set(new_tabs) - set(old_tabs):
        found.add(("added", tab_id))
    kept = [tab_id for tab_id in before["tabOrder"] if tab_id in new_tabs]
    if kept != [tab_id for tab_id in after["tabOrder"] if tab_id in old_tabs]:
        found.add(("order",))
    for tab_id in kept:
        for field in old_tabs[tab_id]:
            if old_tabs[tab_id][field] != new_tabs[tab_id][field]:
                name = field
                if field in SCROLL_KEYS:
                    name = "scroll"
                found.add(("tab", tab_id, name))
    return found


def _changes(before: Dict[str, object], after: Dict[str, object]) -> Set[Change]:
    """What differs between two readings of one view's tabs, each difference named."""
    found = _tab_changes(before, after)
    for name, key in (("page", "referenceViews"), ("dateFilter", "dateFilters"), ("fileFilter", "fileFilters"), ("lock", "searchLocks")):
        for tab_id in set(before[key]) | set(after[key]):
            if _entry(before[key], tab_id) != _entry(after[key], tab_id):
                found.add((name, tab_id))
    for tab_id in set(before["untaggedViews"]) ^ set(after["untaggedViews"]):
        found.add(("untagged", tab_id))
    if before["activeTabId"] != after["activeTabId"]:
        found.add(("active",))
    if before["treeShown"] != after["treeShown"]:
        found.add(("tree",))
    return found


def _nothing(_view: str, _change: Change) -> bool:
    return False


class TabStateUnderSeveralViews(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self._folder = tempfile.TemporaryDirectory()
        set_encryption_required(False)
        self._file_db_path = SafeSession._db_path
        SafeSession._db_path = Path(self._folder.name) / "notes.db"
        SafeSession.use_memory_db()
        edit_locks.reset()
        self.store = TabStateStore()
        self.joined: List[str] = []
        # What each view's page holds: the last answer it took.
        self.known: Dict[str, Dict[str, object]] = {}
        # The tabs each view made as reference pages.
        self.pages: Dict[str, Set[str]] = {view: set() for view in VIEWS}
        # The version at which each tab last came to show other notes (a sort order or a filter).
        self.shows_other_notes_since: Dict[str, int] = {}
        self.version = 0
        # What each calm refusal said, for a failing ordering's report.
        self.refusals: List[str] = []
        # Tabs deleted before a restart: the restarted server never had them, and refuses.
        self.forgotten: Set[str] = set()

    def teardown(self) -> None:
        edit_locks.reset()
        SafeSession.use_file_db()
        SafeSession._db_path = self._file_db_path
        self._folder.cleanup()

    # --- Reading the server, as the test (no page hears of it) ---------------------------------

    def _read(self, view: str) -> Dict[str, object]:
        return _told(self.store.snapshot(view_id=view))

    def _read_all(self) -> Dict[str, Dict[str, object]]:
        return {view: self._read(view) for view in self.joined}

    def _contexts(self, readings: Dict[str, Dict[str, object]]) -> List[str]:
        """The search contexts: the tabs every view sees (a reference page is its view's own)."""
        first = readings[self.joined[0]]["tabOrder"]
        return [tab_id for tab_id in first if all(tab_id in reading["tabs"] for reading in readings.values())]

    def _shared(self, view: str, readings: Dict[str, Dict[str, object]]) -> object:
        """What every view shares, as view sees it: what its shared revision counts changes of."""
        contexts = self._contexts(readings)
        reading = readings[view]
        return (
            contexts,
            [{key: value for key, value in reading["tabs"][tab_id].items() if key not in SCROLL_KEYS} for tab_id in contexts],
            {tab_id: value for tab_id, value in reading["dateFilters"].items() if tab_id in contexts},
            {tab_id: value for tab_id, value in reading["fileFilters"].items() if tab_id in contexts},
            [tab_id for tab_id in reading["untaggedViews"] if tab_id in contexts],
            sorted(reading["searchLocks"]),
        )

    def _join(self, view: str) -> None:
        edit_locks.heard_from(view_id=view, token=f"sign-in-{view}", user_agent="a browser")
        self.known[view] = self.store.snapshot(view_id=view)
        self.joined.append(view)

    @initialize()
    def two_views_open(self) -> None:
        self._join(MAC)
        self._join(PHONE)
        self.version = self.known[MAC]["version"]

    # --- One request, and the rules about it ---------------------------------------------------

    def _tab(self, view: str, index: int) -> str:
        """A tab the view was last told of: maybe deleted since, or closed with its notes."""
        order = self.known[view]["tabOrder"]
        return order[index % len(order)]

    def _ask(
        self, view: str, request: Callable[[], Dict[str, object]], allowed: Allowed, named: Tuple[str, ...],
    ) -> Dict[str, object] | None:
        """view sends request about the tabs named. Returns the answer, or None when it was calmly
        refused."""
        before = self._read_all()
        gone = [tab_id for tab_id in named if tab_id not in before[view]["tabs"]]
        revisions = {other: self.store.shared_revision(view_id=other) for other in self.joined}
        # Rule 1: a calm refusal (a search typed elsewhere is one) leaves no answer; any other
        # exception fails the run. Boundary (declared in .shockharness.toml): the one request.
        answer = None
        try:
            answer = request()
        except InputRejected as refusal:
            self.refusals.append(str(refusal))
        after = self._read_all()
        changes = {other: _changes(before[other], after[other]) for other in self.joined}
        is_changed = any(changes.values())

        # A tab deleted before the view heard of it: whatever is asked changes nothing and is no
        # error (agreed 2026-11-18). The server forgets which tabs are gone when it restarts, and
        # then refuses (a limit left as it is).
        if gone and not set(gone) & self.forgotten:
            assert answer is not None and answer["changed"] is False, f"a request naming deleted tabs {gone} was refused or taken"
        if answer is None or ("changed" in answer and answer["changed"] is False):
            assert not is_changed, f"a request refused or answered as no change changed {changes}"
        # Rule 3.
        for other, found in changes.items():
            unexpected = {change for change in found if not allowed(other, change)}
            assert not unexpected, f"{other} sees changes the request did not name: {unexpected}"
        # Rule 5.
        for other in self.joined:
            rises = int(self._shared(other, before) != self._shared(other, after))
            now = self.store.shared_revision(view_id=other)
            assert now == revisions[other] + rises, f"{other}'s shared revision went {revisions[other]} to {now}, expected a rise of {rises}"
        if answer is not None:
            # Rule 4.
            assert _told(answer) == after[view], "the answer differs from what the server holds"
            rises = int(self._shared(view, before) != self._shared(view, after))
            assert answer["searchContextsRevision"] == {"before": revisions[view], "after": revisions[view] + rises}
            self.known[view] = answer
        # Rule 6.
        version = self.store.snapshot(view_id=view)["version"]
        assert version >= self.version, "the version went down"
        if is_changed:
            assert version > self.version, f"the version stayed at {version} through {changes}"
        self.version = version
        return answer

    def _is_fresh(self, view: str, *tab_ids: str) -> bool:
        """The view asks about tabs the server still shows it."""
        visible = self._read(view)["tabs"]
        return all(tab_id in visible for tab_id in tab_ids)

    # --- The requests ---------------------------------------------------------------------------

    views = st.sampled_from(VIEWS)
    indexes = st.integers(min_value=0, max_value=7)

    @precondition(lambda self: THIRD not in self.joined)
    @rule()
    def a_third_view_opens(self) -> None:
        before = self._read_all()
        self._join(THIRD)
        after = self._read_all()
        assert all(before[view] == after[view] for view in before), "a view opening changed another view's tabs"
        assert self.known[THIRD]["activeTabId"] in self._contexts(after), "a new view starts on a search context"

    @rule(view=views)
    def reread(self, view: str) -> None:
        if view in self.joined:
            self._ask(view, lambda: self.store.snapshot(view_id=view), _nothing, ())

    @rule(view=views, index=indexes, copies_view=st.booleans(), is_page=st.booleans())
    def create_tab(self, view: str, index: int, copies_view: bool, is_page: bool) -> None:
        if view not in self.joined:
            return
        source = self._tab(view, index)
        is_fresh = self._is_fresh(view, source)
        had = set(self._read(view)["tabs"])

        def allowed(other: str, change: Change) -> bool:
            # The new tab, and with a duplicate what its source showed; a page is this view's own.
            is_seen = not (is_page and other != view)
            return is_seen and change[0] in ("added", "dateFilter", "fileFilter", "untagged") and change[1] not in had

        answer = self._ask(view, lambda: self.store.create_tab(view_id=view, copy_from_tab_id=source, copies_view=copies_view, is_page=is_page), allowed, (source,))
        if is_fresh:
            assert answer is not None and answer["newTabId"] in answer["tabs"], "a new tab is made beside a tab that is there"
        if answer is not None and answer["changed"]:
            if is_page:
                self.pages[view].add(answer["newTabId"])

    @rule(view=views, index=indexes)
    def delete_tab(self, view: str, index: int) -> None:
        if view not in self.joined:
            return
        tab_id = self._tab(view, index)
        readings = self._read_all()
        is_fresh = self._is_fresh(view, tab_id)
        is_last_context = self._contexts(readings) == [tab_id]
        showing = {other for other in self.joined if readings[other]["activeTabId"] == tab_id}

        def allowed(other: str, change: Change) -> bool:
            if change == ("removed", tab_id):
                return True
            if change == ("active",):
                return other in showing
            # A page opened from the deleted tab is opened from another now, or ends.
            if change[0] == "page":
                page = readings[other]["referenceViews"][change[1]]
                return tab_id in (change[1], page["fromTabId"], page["originScope"]["scopeTabId"])
            return change[0] in ("dateFilter", "fileFilter", "untagged", "lock") and change[1] == tab_id

        answer = self._ask(view, lambda: self.store.delete_tab(view_id=view, tab_id=tab_id), allowed, (tab_id,))
        if is_fresh:
            assert (answer is not None) == (not is_last_context), "a tab shown to the view is deleted, unless it is the last context"
        if answer is not None:
            assert tab_id not in answer["tabs"]

    @rule(view=views, index=indexes)
    def show_tab(self, view: str, index: int) -> None:
        if view not in self.joined:
            return
        tab_id = self._tab(view, index)
        is_fresh = self._is_fresh(view, tab_id)
        answer = self._ask(view, lambda: self.store.show_tab(view_id=view, tab_id=tab_id), lambda other, change: other == view and change == ("active",), (tab_id,))
        if is_fresh:
            assert answer is not None and answer["activeTabId"] == tab_id, "a view shows the tab it asked for"

    @rule(view=views, index=indexes, search=st.sampled_from(SEARCHES))
    def set_search(self, view: str, index: int, search: str) -> None:
        if view not in self.joined:
            return
        tab_id = self._tab(view, index)
        reading = self._read(view)
        is_fresh = self._is_fresh(view, tab_id)
        is_typed_elsewhere = tab_id in reading["searchLocks"]

        def allowed(other: str, change: Change) -> bool:
            if change == ("tab", tab_id, "searchQuery"):
                return True
            # Another search in a page ends its reference view; the search is this view's to type.
            if change == ("page", tab_id):
                return True
            return change == ("lock", tab_id) and other != view

        answer = self._ask(view, lambda: self.store.set_search(view_id=view, tab_id=tab_id, search_query=search), allowed, (tab_id,))
        if is_fresh and not (is_typed_elsewhere and reading["tabs"][tab_id]["searchQuery"] != search):
            assert answer is not None and answer["tabs"][tab_id]["searchQuery"] == search, "a view's search is taken"
        if is_fresh and is_typed_elsewhere and reading["tabs"][tab_id]["searchQuery"] != search:
            assert answer is None, "a search another view types is not changed"

    @rule(view=views)
    def leave_the_search_box(self, view: str) -> None:
        if view not in self.joined:
            return
        before = self._read_all()
        edit_locks.release_search(view_id=view)
        after = self._read_all()
        for other in self.joined:
            found = _changes(before[other], after[other])
            assert all(change[0] == "lock" and other != view for change in found), f"leaving a search box changed {found}"

    @rule(view=views, index=indexes, to_index=indexes)
    def move_tab(self, view: str, index: int, to_index: int) -> None:
        if view not in self.joined:
            return
        tab_id, to_tab_id = self._tab(view, index), self._tab(view, to_index)
        is_fresh = self._is_fresh(view, tab_id, to_tab_id)
        was = self._read(view)["tabOrder"]
        answer = self._ask(view, lambda: self.store.move_tab(view_id=view, tab_id=tab_id, to_tab_id=to_tab_id), lambda _other, change: change == ("order",), (tab_id, to_tab_id))
        if is_fresh and tab_id != to_tab_id:
            assert answer is not None
            order = answer["tabOrder"]
            beside = 1
            if was.index(tab_id) > was.index(to_tab_id):
                beside = -1
            assert order.index(tab_id) == order.index(to_tab_id) + beside, "a moved tab sits where the other was"
            assert sorted(order) == sorted(was), "a move keeps every tab"

    @rule(view=views, index=indexes, scroll_y=st.sampled_from(SCROLLS))
    def set_scroll(self, view: str, index: int, scroll_y: int) -> None:
        if view not in self.joined:
            return
        tab_id = self._tab(view, index)
        is_fresh = self._is_fresh(view, tab_id)
        is_heard_of_everything = self.known[view]["version"] == self.version
        scroll = {"scrollY": scroll_y, "anchorRootId": None, "scrollAnchor": None}
        read_at_version = self.known[view]["version"]
        answer = self._ask(
            view,
            lambda: self.store.set_scroll(view_id=view, tab_id=tab_id, scroll=scroll, read_at_version=read_at_version),
            lambda other, change: other == view and change == ("tab", tab_id, "scroll"),
            (tab_id,),
        )
        if is_fresh and is_heard_of_everything:
            assert answer is not None and answer["tabs"][tab_id]["scrollY"] == scroll_y, "a scroll measured on the notes shown is taken"
        if tab_id in self.shows_other_notes_since and read_at_version < self.shows_other_notes_since[tab_id]:
            assert answer is None or answer["changed"] is False, "a scroll measured on other notes is not taken"

    @rule(view=views, index=indexes, from_index=indexes, note=st.sampled_from(NOTES), kind=st.sampled_from(("source", "backlinks")))
    def set_reference_page(self, view: str, index: int, from_index: int, note: str, kind: str) -> None:
        if view not in self.joined:
            return
        tab_id, from_tab_id = self._tab(view, index), self._tab(view, from_index)
        readings = self._read_all()
        # The search context the page belongs to, as the page knows it: the tab it is opened from,
        # or that tab's own when it is a page.
        known = self.known[view]
        scope_tab_id = from_tab_id
        if from_tab_id in known["referenceViews"]:
            scope_tab_id = known["referenceViews"][from_tab_id]["originScope"]["scopeTabId"]
        if scope_tab_id in self.pages[view] or scope_tab_id not in known["tabs"]:
            return
        # A page is never its own search context, nor opened from a page opened from it. The
        # server takes both (found 2026-11-18, see the plan's findings); the page sends neither.
        opened_from = from_tab_id
        while opened_from in known["referenceViews"] and opened_from != tab_id:
            opened_from = known["referenceViews"][opened_from]["fromTabId"]
        if tab_id in (scope_tab_id, opened_from):
            return
        # A search context never becomes a page, whatever its search (agreed 2026-11-18).
        is_context = tab_id in self._contexts(readings)
        origin = known["tabs"][scope_tab_id]
        scope = {
            "scopeTabId": scope_tab_id, "searchQuery": origin["searchQuery"], "sortMode": origin["sortMode"],
            "isUntaggedView": scope_tab_id in known["untaggedViews"],
        }

        def allowed(other: str, change: Change) -> bool:
            return other == view and change in (("page", tab_id), ("tab", tab_id, "searchQuery"))

        answer = self._ask(
            view,
            lambda: self.store.set_reference_page(
                view_id=view, tab_id=tab_id, from_tab_id=from_tab_id, reference_query=note, view_kind=kind, origin_scope=scope,
            ),
            allowed,
            (tab_id, from_tab_id, scope_tab_id),
        )
        if is_context:
            # Refused, or "no change" when it names a tab deleted a moment ago.
            assert answer is None or answer["changed"] is False, "a search context was taken as a reference page"
        if answer is not None and answer["changed"]:
            assert answer["referenceViews"][tab_id]["referenceQuery"] == answer["tabs"][tab_id]["searchQuery"] == note

    @rule(view=views, index=indexes, sort_mode=st.sampled_from(SORT_MODES))
    def set_sort_mode(self, view: str, index: int, sort_mode: str) -> None:
        if view not in self.joined:
            return
        tab_id = self._tab(view, index)
        is_fresh = self._is_fresh(view, tab_id)
        answer = self._ask(
            view, lambda: self.store.set_sort_mode(view_id=view, tab_id=tab_id, sort_mode=sort_mode),
            lambda _other, change: change in (("tab", tab_id, "sortMode"), ("tab", tab_id, "scroll")),
            (tab_id,),
        )
        if is_fresh:
            assert answer is not None and answer["tabs"][tab_id]["sortMode"] == sort_mode
        if answer is not None and answer["changed"]:
            self.shows_other_notes_since[tab_id] = self.version

    @rule(view=views, index=indexes, file_filter=st.sampled_from(FILE_FILTERS))
    def set_file_filter(self, view: str, index: int, file_filter: str | None) -> None:
        if view not in self.joined:
            return
        tab_id = self._tab(view, index)
        is_fresh = self._is_fresh(view, tab_id)
        answer = self._ask(
            view, lambda: self.store.set_file_filter(view_id=view, tab_id=tab_id, file_filter=file_filter),
            lambda _other, change: change in (("fileFilter", tab_id), ("tab", tab_id, "sortMode"), ("tab", tab_id, "scroll")),
            (tab_id,),
        )
        if is_fresh:
            assert answer is not None and (tab_id in answer["fileFilters"]) == (file_filter is not None)
        if answer is not None and answer["changed"]:
            self.shows_other_notes_since[tab_id] = self.version

    @rule(view=views, index=indexes, is_untagged_view=st.booleans())
    def set_untagged_view(self, view: str, index: int, is_untagged_view: bool) -> None:
        if view not in self.joined:
            return
        tab_id = self._tab(view, index)
        is_fresh = self._is_fresh(view, tab_id)
        answer = self._ask(
            view, lambda: self.store.set_untagged_view(view_id=view, tab_id=tab_id, is_untagged_view=is_untagged_view),
            lambda _other, change: change in (("untagged", tab_id), ("tab", tab_id, "scroll")),
            (tab_id,),
        )
        if is_fresh:
            assert answer is not None and (tab_id in answer["untaggedViews"]) == is_untagged_view
        if answer is not None and answer["changed"]:
            self.shows_other_notes_since[tab_id] = self.version

    @rule(view=views, is_shown=st.booleans())
    def set_tree_shown(self, view: str, is_shown: bool) -> None:
        if view not in self.joined:
            return
        answer = self._ask(view, lambda: self.store.set_tree_shown(view_id=view, is_shown=is_shown), lambda other, change: other == view and change == ("tree",), ())
        assert answer is not None and answer["treeShown"] is is_shown

    # Rule 8. The tabs a vault starts with are saved with their first change, so a restart
    # before any change starts again (found 2026-11-18, left as it is: see the plan's findings).
    @precondition(lambda self: self.version > 0)
    @rule()
    def the_server_restarts(self) -> None:
        before = self._read_all()
        restarted = TabStateStore()
        session = SafeSession()
        with SafeSession.allow_reads("tests:tab_state_simulation"):
            restarted.bootstrap(connection=session.connection())
        session.close()
        self.store = restarted
        # Which scrolls were measured on other notes is not kept through a restart.
        self.shows_other_notes_since = {}
        after = self._read_all()
        # Tabs a view still knows of that are gone: the restarted server never had them.
        there = {tab_id for reading in after.values() for tab_id in reading["tabs"]}
        self.forgotten |= {tab_id for known in self.known.values() for tab_id in known["tabs"]} - there
        for view in self.joined:
            assert before[view] == after[view], f"a restart changed {view}'s tabs: {_changes(before[view], after[view])}"

    # --- Rule 7 ---------------------------------------------------------------------------------

    @invariant()
    def the_state_is_well_formed(self) -> None:
        if not self.joined:
            return
        readings = self._read_all()
        contexts = self._contexts(readings)
        assert contexts, "there is always a search context"
        for view, reading in readings.items():
            order = reading["tabOrder"]
            assert len(set(order)) == len(order) and set(order) == set(reading["tabs"]), "the order lists each tab once"
            assert [tab_id for tab_id in order if tab_id in contexts] == contexts, "every view has the contexts in one order"
            assert reading["activeTabId"] in order, f"{view} shows a tab it cannot see"
            assert reading["pageTabIds"] == [tab_id for tab_id in order if tab_id not in contexts], f"{view} is told its own pages"
            for key in ("dateFilters", "fileFilters", "untaggedViews", "referenceViews"):
                assert set(reading[key]) <= set(order), f"{key} names a tab {view} cannot see"
            for tab_id, page in reading["referenceViews"].items():
                assert tab_id not in contexts, "a reference page is its view's own"
                assert page["fromTabId"] in order, "a reference page is opened from a tab its view sees"
                assert page["originScope"]["scopeTabId"] in contexts, "a reference page's search context exists"
                assert page["referenceQuery"] == reading["tabs"][tab_id]["searchQuery"], "a page shows its reference"
            for tab_id in contexts:
                shared = [{key: value for key, value in other["tabs"][tab_id].items() if key not in SCROLL_KEYS} for other in readings.values()]
                assert all(entry == shared[0] for entry in shared), "every view has the same search and order for a context"


def test_the_tab_state_holds_its_rules_under_any_ordering() -> None:
    chosen = settings(
        max_examples=EXAMPLES_IN_THE_UNIT_RUN, stateful_step_count=STEPS_IN_THE_UNIT_RUN, deadline=None,
        derandomize=True, database=None, suppress_health_check=list(HealthCheck),
    )
    if LONG_RUN_EXAMPLES_VARIABLE in os.environ:
        chosen = settings(
            max_examples=int(os.environ[LONG_RUN_EXAMPLES_VARIABLE]), stateful_step_count=STEPS_IN_A_LONG_RUN,
            deadline=None, database=None, suppress_health_check=list(HealthCheck),
        )
    run_state_machine_as_test(TabStateUnderSeveralViews, settings=chosen)
