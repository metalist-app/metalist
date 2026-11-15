"""One editor per root note (multi-view editing step 4; docs/ready-to-build/multi-view-editing.md §3
and "Step 4's cases").

A view (a browser tab or the installed phone app, named by its X-Metalist-Tab-Id) editing any note
under a root note holds that root: every other view's change to it is refused, its content, tags,
collapse state and children at any depth, its deletion, and moving notes into or out of it. Moving
the root itself among the roots, and changing its neighbours, stay open. The note writes check it
(app/db/notes_sql.py, require_writable): the one place every change to a note passes.

A view says what it edits in each status check (every 2 seconds while shown, about once a minute
while hidden) and each view request; its lock lasts while it is heard from and lapses
LEASE_SECONDS after. Take Over hands a root to another view: the holder may still save for
HANDOVER_SECONDS (it is told at its next check and saves its typing), then the new view edits.

A search being typed locks its search context's search the same way (case 10), for
SEARCH_LOCK_SECONDS after the last change or until the box is left.

Work with no view (background work, startup) and rewrites that leave every note's text as it was
(storage_rewrite: a new password re-encrypting the notes) are not checked.
"""

from __future__ import annotations

import hashlib
import re
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Dict, Iterator, Optional, Protocol

from app.services.input_errors import InputRejected

NO_VIEW = ""
# A lock outlasts about three missed checks of a hidden tab (browsers slow its timers to once a minute).
LEASE_SECONDS = 180
# How long the view a root was taken from may still save it.
HANDOVER_SECONDS = 5
# Told it was taken over this close to the end of its handover, a view keeps its typing for copying
# rather than save it too late.
SAVE_MARGIN_SECONDS = 1
SEARCH_LOCK_SECONDS = 5

IN_ANOTHER_TAB = "in another tab"
ON_YOUR_PHONE = "on your phone"
ON_ANOTHER_COMPUTER = "on another computer"
_PHONE_AGENT = re.compile(r"iPhone|iPad|Android|Mobile", re.IGNORECASE)


class SearchLockedElsewhere(InputRejected):
    """A search typed while another view types that context's search."""


class ComposerLockedElsewhere(InputRejected):
    """A question typed for the AI while another view types one (step 5, case 11)."""


class NoteLockedElsewhere(InputRejected):
    """A change to a root another view is editing: answered as rejected input (main.py), naming the
    root so the browser opens its marker."""

    def __init__(self, *, root_id: str, where: str) -> None:
        super().__init__(f"This note is being edited {where}. Try again once editing ends there.")
        self.root_id = root_id
        self.where = where


@dataclass
class _View:
    browser: str
    is_phone: bool
    heard_at: float


@dataclass
class _Lock:
    view_id: str
    # Taken over: the view it was taken from, which may save until the handover ends.
    handing_over_from: str
    handover_until: float


@dataclass
class _SearchLock:
    view_id: str
    until: float


@dataclass
class _ComposerLock:
    view_id: str
    text: str


@dataclass(frozen=True)
class _RequestView:
    view_id: str


_request_view: ContextVar[_RequestView] = ContextVar("edit_locks_request_view", default=_RequestView(view_id=NO_VIEW))
_rewriting_storage: ContextVar[bool] = ContextVar("edit_locks_rewriting_storage", default=False)


def browser_of(token: str) -> str:
    """The sign-in a view uses, as a digest: views of one browser share it."""
    assert isinstance(token, str) and token, "a view is signed in"
    return hashlib.sha256(token.encode()).hexdigest()


class _NoteRecord(Protocol):
    id: str
    parent_id: Optional[str]


class _NoteTree(Protocol):
    def get_note(self, note_id: str) -> _NoteRecord: ...

    def has_note(self, note_id: str) -> bool: ...


class _Notes:
    """The note tree the locks read. The note store hands itself over when it loads
    (note_store.py): it imports the note writes, which check here, so this module cannot import it."""

    tree: Optional[_NoteTree] = None


def attach_note_tree(tree: _NoteTree) -> None:
    assert _Notes.tree is None, "the note store attaches once"
    _Notes.tree = tree


def _tree() -> _NoteTree:
    assert _Notes.tree is not None, "the note store attaches itself when it loads"
    return _Notes.tree


def root_of(note_id: str) -> str:
    current = _tree().get_note(note_id)
    while current.parent_id is not None:
        current = _tree().get_note(current.parent_id)
    return current.id


class EditLocks:
    def __init__(self) -> None:
        self._lock = RLock()
        self._views: Dict[str, _View] = {}
        self._roots: Dict[str, _Lock] = {}
        self._searches: Dict[str, _SearchLock] = {}
        # The AI message box: the view typing a question, and its text, shown in the others.
        self._composer: Optional[_ComposerLock] = None
        # Views whose root was taken over, with where it went: told once, at their next check.
        self._taken_from: Dict[str, str] = {}
        # Roots another view moved while they were edited: kept in place on the editor's screen.
        self._moved_elsewhere: set[str] = set()
        self._revision = 0

    # --- Who asks ----------------------------------------------------------------------------

    def enter_request(self, *, view_id: str, token: str, user_agent: str) -> Token:
        """A signed-in view's request: it is heard from, and its writes are checked as its own."""
        self.heard_from(view_id=view_id, token=token, user_agent=user_agent)
        return _request_view.set(_RequestView(view_id=view_id))

    def heard_from(self, *, view_id: str, token: str, user_agent: str) -> None:
        """Any request of a signed-in view, its status checks included: its locks last."""
        if not isinstance(view_id, str) or not view_id:
            raise ValueError("a view's request names the view")
        with self._lock:
            self._views[view_id] = _View(
                browser=browser_of(token), is_phone=_PHONE_AGENT.search(user_agent) is not None, heard_at=monotonic(),
            )

    @staticmethod
    def leave_request(token: Token) -> None:
        _request_view.reset(token)

    @staticmethod
    def request_view_id() -> str:
        return _request_view.get().view_id

    @staticmethod
    @contextmanager
    def storage_rewrite() -> Iterator[None]:
        """Writes that leave every note as the user sees it (re-encryption): not checked."""
        token = _rewriting_storage.set(True)
        try:
            yield
        finally:
            _rewriting_storage.reset(token)

    def _where_locked(self, view_id: str, holder_id: str) -> str:
        holder = self._views[holder_id]
        if view_id in self._views and self._views[view_id].browser == holder.browser:
            return IN_ANOTHER_TAB
        if holder.is_phone:
            return ON_YOUR_PHONE
        return ON_ANOTHER_COMPUTER

    def _is_heard_locked(self, view_id: str, now: float) -> bool:
        return view_id in self._views and now - self._views[view_id].heard_at < LEASE_SECONDS

    def _live_lock_locked(self, root_id: str, now: float) -> Optional[_Lock]:
        if root_id not in self._roots:
            return None
        lock = self._roots[root_id]
        if self._is_heard_locked(lock.view_id, now):
            return lock
        self._release_root_locked(root_id)
        return None

    def _release_root_locked(self, root_id: str) -> None:
        del self._roots[root_id]
        self._moved_elsewhere.discard(root_id)
        self._revision += 1

    # --- Editing -----------------------------------------------------------------------------

    def sync_editing(self, *, view_id: str, note_id: str, tells_taken: bool) -> Dict[str, object]:
        """What the view edits now ("" for nothing): it holds that note's root, or is told why not.
        Answers {} when it holds it (or edits nothing); {"rootId", "lockedWhere"} when another view
        holds it; with tells_taken (its status check), {"rootId", "takenWhere", "maySave"} once when
        it was taken over from this view (maySave: its typing can still be saved)."""
        with self._lock:
            now = monotonic()
            held = [root_id for root_id, lock in self._roots.items() if lock.view_id == view_id]
            if view_id in self._taken_from and not tells_taken:
                return {}
            if view_id in self._taken_from:
                where = self._taken_from.pop(view_id)
                for root_id, lock in self._roots.items():
                    if lock.handing_over_from == view_id:
                        may_save = now + SAVE_MARGIN_SECONDS < lock.handover_until
                        return {"rootId": root_id, "takenWhere": where, "maySave": may_save}
                return {"rootId": "", "takenWhere": where, "maySave": False}
            # Taken over from this view, which has now left that root: the handover is done.
            for root_id, lock in self._roots.items():
                if lock.handing_over_from == view_id and (note_id == "" or root_of(note_id) != root_id):
                    lock.handing_over_from = NO_VIEW
            if note_id == "" or not _tree().has_note(note_id):
                for root_id in held:
                    self._release_root_locked(root_id)
                return {}
            root_id = root_of(note_id)
            lock = self._live_lock_locked(root_id, now)
            if lock is not None and lock.view_id != view_id:
                return {"rootId": root_id, "lockedWhere": self._where_locked(view_id, lock.view_id)}
            for other in held:
                if other != root_id:
                    self._release_root_locked(other)
            if lock is None:
                self._roots[root_id] = _Lock(view_id=view_id, handing_over_from=NO_VIEW, handover_until=0.0)
                self._revision += 1
            return {}

    def take_over(self, *, view_id: str, note_id: str) -> bool:
        """Take the root of note_id for this view. True once the view it was taken from has let it
        go (saved and left, or its handover time passed): then this view edits."""
        with self._lock:
            now = monotonic()
            root_id = root_of(note_id)
            lock = self._live_lock_locked(root_id, now)
            if lock is None:
                self._roots[root_id] = _Lock(view_id=view_id, handing_over_from=NO_VIEW, handover_until=0.0)
                self._revision += 1
                return True
            if lock.view_id != view_id:
                where = self._where_locked(lock.view_id, view_id)
                self._taken_from[lock.view_id] = where
                self._roots[root_id] = _Lock(
                    view_id=view_id, handing_over_from=lock.view_id, handover_until=now + HANDOVER_SECONDS,
                )
                self._moved_elsewhere.discard(root_id)
                self._revision += 1
                return False
            if lock.handing_over_from != NO_VIEW and now >= lock.handover_until:
                lock.handing_over_from = NO_VIEW
            return lock.handing_over_from == NO_VIEW

    def locked_roots_for(self, *, view_id: str) -> Dict[str, str]:
        """The roots other views edit, with where, as this view shows them."""
        with self._lock:
            now = monotonic()
            shown: Dict[str, str] = {}
            for root_id in list(self._roots):
                lock = self._live_lock_locked(root_id, now)
                if lock is not None and lock.view_id != view_id:
                    shown[root_id] = self._where_locked(view_id, lock.view_id)
            return shown

    def was_moved_elsewhere(self, *, root_id: str) -> bool:
        with self._lock:
            return root_id in self._moved_elsewhere

    def revision(self) -> int:
        """Rises when a lock is taken, released or lapses: views show the markers again."""
        with self._lock:
            now = monotonic()
            for root_id in list(self._roots):
                self._live_lock_locked(root_id, now)
            for tab_id in list(self._searches):
                self._live_search_lock_locked(tab_id, now)
            return self._revision

    # --- Writes ------------------------------------------------------------------------------

    def _require_root_writable_locked(self, root_id: str, view_id: str, now: float) -> None:
        lock = self._live_lock_locked(root_id, now)
        if lock is None or lock.view_id == view_id:
            return
        if lock.handing_over_from == view_id and now < lock.handover_until:
            return
        raise NoteLockedElsewhere(root_id=root_id, where=self._where_locked(view_id, lock.view_id))

    def require_writable(self, *, note_id: str) -> None:
        """A change to this note's text, tags, collapse state, or its place under its parent."""
        view_id = self.request_view_id()
        if view_id == NO_VIEW or _rewriting_storage.get() or not _tree().has_note(note_id):
            return
        with self._lock:
            self._require_root_writable_locked(root_of(note_id), view_id, monotonic())

    def require_parent_writable(self, *, parent_id: Optional[str]) -> None:
        """A note added under parent_id, or moved there."""
        if parent_id is not None:
            self.require_writable(note_id=parent_id)

    def require_links_writable(self, *, note_id: str, changes: Dict[str, object]) -> None:
        """A note's place changing (parent, neighbours) or its collapse state. A root's neighbours
        changing is no change to it: moving a root that is being edited stays open."""
        view_id = self.request_view_id()
        if view_id == NO_VIEW or _rewriting_storage.get() or not _tree().has_note(note_id):
            return
        record = _tree().get_note(note_id)
        is_root_staying_root = record.parent_id is None and (
            "parent_id" not in changes or changes["parent_id"] is None
        )
        if is_root_staying_root and "is_collapsed" not in changes:
            with self._lock:
                lock = self._live_lock_locked(note_id, monotonic())
                if lock is not None and lock.view_id != view_id and "prev_id" in changes:
                    self._moved_elsewhere.add(note_id)
            return
        self.require_writable(note_id=note_id)
        if "parent_id" in changes:
            parent_id = changes["parent_id"]
            assert parent_id is None or isinstance(parent_id, str), "a parent is a note id or none"
            self.require_parent_writable(parent_id=parent_id)

    # --- Search lock -------------------------------------------------------------------------

    def _live_search_lock_locked(self, tab_id: str, now: float) -> Optional[_SearchLock]:
        if tab_id not in self._searches:
            return None
        lock = self._searches[tab_id]
        if now < lock.until and self._is_heard_locked(lock.view_id, now):
            return lock
        del self._searches[tab_id]
        self._revision += 1
        return None

    def note_search_typed(self, *, view_id: str, tab_id: str) -> None:
        """This view changed the search of tab_id: refused while another view types it, else locked
        for SEARCH_LOCK_SECONDS more."""
        with self._lock:
            now = monotonic()
            lock = self._live_search_lock_locked(tab_id, now)
            if lock is not None and lock.view_id != view_id:
                raise SearchLockedElsewhere(f"This search is being typed {self._where_locked(view_id, lock.view_id)}.")
            if lock is None:
                self._revision += 1
            self._searches[tab_id] = _SearchLock(view_id=view_id, until=now + SEARCH_LOCK_SECONDS)

    def release_search(self, *, view_id: str) -> None:
        """The view left its search box."""
        with self._lock:
            for tab_id in [tab_id for tab_id, lock in self._searches.items() if lock.view_id == view_id]:
                del self._searches[tab_id]
                self._revision += 1

    def searches_locked(self) -> list[str]:
        """The search contexts whose search a view is typing, by id."""
        with self._lock:
            now = monotonic()
            return sorted(tab_id for tab_id in list(self._searches) if self._live_search_lock_locked(tab_id, now) is not None)

    def search_locks_for(self, *, view_id: str) -> Dict[str, str]:
        with self._lock:
            now = monotonic()
            shown: Dict[str, str] = {}
            for tab_id in list(self._searches):
                lock = self._live_search_lock_locked(tab_id, now)
                if lock is not None and lock.view_id != view_id:
                    shown[tab_id] = self._where_locked(view_id, lock.view_id)
            return shown

    # --- AI message box ----------------------------------------------------------------------

    def _live_composer_locked(self, now: float) -> Optional[_ComposerLock]:
        composer = self._composer
        if composer is None:
            return None
        if self._is_heard_locked(composer.view_id, now):
            return composer
        self._composer = None
        self._revision += 1
        return None

    def note_composer_typed(self, *, view_id: str, text: str) -> None:
        """This view types a question for the AI: refused while another view types one, else the
        box is this view's, its text shown in the others, until it is left or sent (case 11)."""
        if not isinstance(text, str):
            raise InputRejected("The question must be text.")
        with self._lock:
            composer = self._live_composer_locked(monotonic())
            if composer is not None and composer.view_id != view_id:
                raise ComposerLockedElsewhere(
                    f"A question is being typed {self._where_locked(view_id, composer.view_id)}.")
            if composer is None:
                self._revision += 1
            self._composer = _ComposerLock(view_id=view_id, text=text)

    def release_composer(self, *, view_id: str) -> None:
        """The view left its message box, or sent the question."""
        with self._lock:
            if self._composer is not None and self._composer.view_id == view_id:
                self._composer = None
                self._revision += 1

    def composer_for(self, *, view_id: str) -> Dict[str, str]:
        """Another view's question being typed, with where, as this view shows it; {} for none."""
        with self._lock:
            composer = self._live_composer_locked(monotonic())
            if composer is None or composer.view_id == view_id:
                return {}
            return {"where": self._where_locked(view_id, composer.view_id), "text": composer.text}

    # --- Ending ------------------------------------------------------------------------------

    def forget_browsers(self, *, tokens: list[str]) -> None:
        """Signed out: every view of these sign-ins lets go of what it edits."""
        browsers = {browser_of(token) for token in tokens}
        with self._lock:
            gone = {view_id for view_id, view in self._views.items() if view.browser in browsers}
            self._forget_views_locked(gone)

    def forget_all_but(self, *, token: str) -> None:
        """Every sign-in but this one ended (a new password)."""
        kept = browser_of(token)
        with self._lock:
            self._forget_views_locked({view_id for view_id, view in self._views.items() if view.browser != kept})

    def reset(self) -> None:
        """The vault locked, or its runtime started again."""
        with self._lock:
            self._forget_views_locked(set(self._views))

    def _forget_views_locked(self, gone: set[str]) -> None:
        for root_id in [root_id for root_id, lock in self._roots.items() if lock.view_id in gone]:
            self._release_root_locked(root_id)
        for tab_id in [tab_id for tab_id, lock in self._searches.items() if lock.view_id in gone]:
            del self._searches[tab_id]
            self._revision += 1
        if self._composer is not None and self._composer.view_id in gone:
            self._composer = None
            self._revision += 1
        for view_id in gone:
            del self._views[view_id]
            if view_id in self._taken_from:
                del self._taken_from[view_id]


edit_locks = EditLocks()
