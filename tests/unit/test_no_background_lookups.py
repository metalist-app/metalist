"""Unit tests never start a real link-title or site-icon lookup (tests/unit/conftest.py).

Unit tests run outside the server's test mode, so a render that finds an unknown link asks
for its title or its site's icon, and the lookup ran on the background workers: it could
reach the real network, and it ran on into whatever test came next. On 2026-10-26 a
leftover lookup for arxiv.org's icon landed in another test's fake network on CI (macOS,
Python 3.11). Every unit test gets an executor that records the lookups it is asked for and
runs none.
"""

from __future__ import annotations

import sqlite3

import app.services.link_titles as link_titles
from app.db.schema import initialize_schema
from app.security.encryption import clear_encryption_key
from app.services.content_formatting import format_note_content_for_view
from app.services.link_titles import link_title_store


def test_a_render_asks_for_lookups_and_none_runs() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    initialize_schema(connection)
    clear_encryption_key()
    link_title_store.bootstrap(connection=connection)
    try:
        format_note_content_for_view(
            content_html='<div>https://example.org/untitled</div><div><a href="https://example.net/x">Label</a></div>',
            tags="", redact_credentials=False,
        )
    finally:
        link_title_store.reset()
        connection.close()

    asked = [(job.__name__, args[0]) for job, args in link_titles._FETCHER_EXECUTOR.submitted]
    assert asked == [("_run_fetch_job", "https://example.org/untitled"), ("_run_fetch_job", "https://example.net")]
