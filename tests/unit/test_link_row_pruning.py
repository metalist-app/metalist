"""Link titles and site icons are cached per address and per site; once no note links there,
their rows go (agreed 2026-11-11, docs/ready-to-build/unbounded-growth-audit.md, D1 and D2).
A link that comes back is looked up again."""

from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
import sqlite3

from PIL import Image
import pytest

import app.services.link_icons as link_icons
import app.services.link_titles as link_titles
from app.db.link_icons_sql import fetch_all_link_icon_rows
from app.db.link_titles_sql import fetch_all_link_title_rows
from app.db.schema import initialize_schema
from app.security.encryption import clear_encryption_key
from app.services.content_formatting import urls_linked_in
from app.services.link_icons import LinkIconFetchResult, link_icon_store
from app.services.link_row_pruning import forget_link_rows_no_note_uses
from app.services.link_titles import _LinkTitleFetchResult, link_title_store


@pytest.fixture
def link_database(monkeypatch: pytest.MonkeyPatch):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    initialize_schema(connection)

    @contextmanager
    def fake_begin_writer():
        yield connection

    monkeypatch.setattr(link_icons, "begin_writer", fake_begin_writer)
    monkeypatch.setattr(link_titles, "begin_writer", fake_begin_writer)
    clear_encryption_key()
    link_title_store.bootstrap(connection=connection)
    yield connection
    link_title_store.reset()
    clear_encryption_key()
    connection.close()


def _icon_base64() -> str:
    buffer = BytesIO()
    Image.new("RGBA", (32, 32), "red").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _title(url: str, title: str) -> None:
    link_title_store.apply_fetch_result(
        _LinkTitleFetchResult(url=url, title=title, status="ok", last_error_kind=None),
    )


def _icon(origin: str) -> None:
    link_icon_store.apply_fetch_result(
        LinkIconFetchResult(origin=origin, icon_png_base64=_icon_base64(), status="ok", last_error_kind=None),
    )


def _title_urls(connection: sqlite3.Connection) -> set[str]:
    return {str(row["url"]) for row in fetch_all_link_title_rows(connection)}


def _icon_origins(connection: sqlite3.Connection) -> set[str]:
    return {row.origin for row in fetch_all_link_icon_rows(connection)}


def test_a_note_s_links_and_bare_addresses_are_both_found() -> None:
    content = (
        '<p><a href="https://linked.example/page?a=1&amp;b=2">text</a> and '
        "https://bare.example/path plus no link</p>"
    )

    assert urls_linked_in(content) == frozenset({"https://linked.example/page?a=1&b=2", "https://bare.example/path"})


def test_titles_of_addresses_no_note_links_to_go_and_the_rest_stay(link_database: sqlite3.Connection) -> None:
    _title("https://kept.example/page", "Kept")
    _title("https://gone.example/page", "Gone")

    removed = forget_link_rows_no_note_uses(note_contents=["<p>see https://kept.example/page</p>"])

    assert removed == 1
    assert _title_urls(link_database) == {"https://kept.example/page"}
    assert link_title_store.get_ok_title("https://kept.example/page") == "Kept"
    assert link_title_store.get_ok_title("https://gone.example/page") is None


def test_icons_of_sites_no_note_links_to_go_and_the_rest_stay(link_database: sqlite3.Connection) -> None:
    _icon("https://kept.example")
    _icon("https://gone.example")

    removed = forget_link_rows_no_note_uses(
        note_contents=['<p><a href="https://kept.example/any/page">a page there</a></p>'],
    )

    assert removed == 1
    assert _icon_origins(link_database) == {"https://kept.example"}
    assert link_icon_store.get_icon_base64("https://kept.example/x") is not None
    assert link_icon_store.get_icon_base64("https://gone.example/x") is None


def test_an_address_being_looked_up_now_stays(link_database: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    _title("https://busy.example/page", "Busy")
    monkeypatch.setattr(link_titles, "TEST_MODE", False)
    monkeypatch.setattr(link_titles.link_title_fetcher, "submit", lambda normalized_url, generation: None)
    # A failed lookup is due again at once, so asking for it puts it in flight.
    link_title_store.apply_fetch_result(
        _LinkTitleFetchResult(url="https://busy.example/page", title=None, status="failed", last_error_kind="timeout"),
    )
    monkeypatch.setattr(link_titles, "_effective_next_check_after", lambda *, record: datetime(2000, 1, 1, tzinfo=timezone.utc))
    link_title_store.maybe_enqueue_fetch("https://busy.example/page")

    assert forget_link_rows_no_note_uses(note_contents=[]) == 0
    assert _title_urls(link_database) == {"https://busy.example/page"}


def test_nothing_goes_while_the_titles_cannot_be_read(link_database: sqlite3.Connection) -> None:
    _title("https://kept.example/page", "Kept")
    link_title_store.reset()

    assert forget_link_rows_no_note_uses(note_contents=[]) == 0
    assert _title_urls(link_database) == {"https://kept.example/page"}
