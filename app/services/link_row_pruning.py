"""Link titles and site icons no note links to any more go (agreed 2026-11-11,
docs/ready-to-build/unbounded-growth-audit.md, D1 and D2).

Both are cached per address (`link_titles`) and per site (`link_icons`) when a note shows a
link, and nothing removed a row once the last note with that link went: they only grew. Each
time the notes have been loaded (startup, unlock), once the page has started, a thread reads
which addresses and sites the notes link to and drops the rest. A link that comes back is
looked up again, as a new one is.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
import re
from threading import Thread

from app.security.sensitive_cache import sensitive_caches_enabled
from app.services.bulk_operation import bulk_operation_guard
from app.services.content_formatting import urls_linked_in
from app.services.link_icons import icon_origin_for_url, link_icon_store
from app.services.link_titles import link_title_store, normalize_url_for_link_title
from app.services.note_store import NoteRecord, store
from app.services.requests_in_flight import requests_in_flight
from app.services.runtime_generation import current_generation


# Most notes link nowhere: only text with a web address in it is read in full (1.3 s for
# 109,000 notes otherwise, beside the page's first requests). A miss only costs a lookup again.
_MAY_LINK_RE = re.compile(r"https?://", re.IGNORECASE)
# The scan gives way to the requests this often.
_NOTES_BETWEEN_GIVING_WAY = 1000


def _linked_urls_and_sites(note_contents: Iterable[str]) -> tuple[frozenset[str], frozenset[str]]:
    """Every address the notes link to, as the title store keys it, and every site, as the
    icon store keys it."""
    urls: set[str] = set()
    sites: set[str] = set()
    for content in note_contents:
        if _MAY_LINK_RE.search(content) is None:
            continue
        for url in urls_linked_in(content):
            normalized_url = normalize_url_for_link_title(url)
            if normalized_url is not None:
                urls.add(normalized_url)
            site = icon_origin_for_url(url)
            if site is not None:
                sites.add(site)
    return frozenset(urls), frozenset(sites)


def _forget_unlinked(*, linked_urls: frozenset[str], linked_sites: frozenset[str]) -> int:
    return link_title_store.forget_urls_not_in(linked_urls) + link_icon_store.forget_origins_not_in(linked_sites)


def forget_link_rows_no_note_uses(*, note_contents: Iterable[str]) -> int:
    """Drop the titles and icons these notes do not link to. Returns how many rows went."""
    linked_urls, linked_sites = _linked_urls_and_sites(note_contents)
    return _forget_unlinked(linked_urls=linked_urls, linked_sites=linked_sites)


def _contents_giving_way(records: Iterable[NoteRecord]) -> Iterator[str]:
    """The notes' text, giving way to the requests every few notes (requests_in_flight.py)."""
    for index, record in enumerate(records):
        if index % _NOTES_BETWEEN_GIVING_WAY == 0:
            requests_in_flight.give_way()
        yield record.content


def _forget_once_notes_are_loaded() -> None:
    generation = current_generation()
    # Read outside the lock, from a snapshot: a whole vault's text takes a while.
    linked_urls, linked_sites = _linked_urls_and_sites(_contents_giving_way(store.snapshot().values()))
    with bulk_operation_guard.lock:
        # A lock or login since the snapshot: its notes are not the vault's now.
        if generation != current_generation() or not sensitive_caches_enabled():
            return
        _forget_unlinked(linked_urls=linked_urls, linked_sites=linked_sites)


def start_link_row_pruning() -> None:
    """Run once the notes are loaded and the page has started (app/main.py registers it with
    auth_cache_state.after_page_ready), on a thread of its own."""
    Thread(target=_forget_once_notes_are_loaded, name="metalist-link-row-pruning", daemon=True).start()
