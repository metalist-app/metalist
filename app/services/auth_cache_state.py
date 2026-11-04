"""In-memory flag tracking whether the cache was hydrated post-login.

This lets the /auth/login endpoint avoid re-reading sqlite every time a user
logs in. The app starts with the flag cleared. Once the cache has been
refreshed using a real DEK, we mark it so future logins can skip the expensive
populate step. If we ever need to force a refresh (password reset, etc.), call
``reset_cache_state``.
"""

from __future__ import annotations

from threading import Lock
from typing import Callable, List

_cache_ready = False  # shockharness: ignore[STATE001] reason="every access holds _cache_lock"
_cache_lock = Lock()
# Work to start once the notes are loaded (on_cache_ready): caches built ahead of the first
# request that needs them, so no request waits for a whole vault's worth.
_ready_listeners: List[Callable[[], None]] = []


def cache_refresh_needed() -> bool:
    with _cache_lock:
        return not _cache_ready


def mark_cache_ready() -> None:
    global _cache_ready
    with _cache_lock:
        _cache_ready = True
        listeners = list(_ready_listeners)
    for listener in listeners:
        listener()


def on_cache_ready(listener: Callable[[], None]) -> None:
    """Call listener each time the notes have been loaded (startup, unlock, recovery)."""
    if not callable(listener):
        raise TypeError("on_cache_ready requires a callable")
    with _cache_lock:
        _ready_listeners.append(listener)


def reset_cache_state() -> None:
    global _cache_ready
    with _cache_lock:
        _cache_ready = False
