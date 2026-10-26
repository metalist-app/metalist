"""Every web link looks the same (docs/ui/content-formatting.md, "Links In View Mode"; agreed
2026-10-26): its site's icon, its text, then " · domain", whether the note holds a bare
address (its fetched title is the text) or a link with its own text, alone on its line or
inside a sentence. Links that are not web pages stay as they are."""

from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
import sqlite3

from PIL import Image
import pytest

import app.services.content_formatting as content_formatting
import app.services.link_icons as link_icons
import app.services.link_titles as link_titles
from app.db.link_titles_sql import insert_link_title_row
from app.db.schema import initialize_schema
from app.security.encryption import clear_encryption_key
from app.services.content_formatting import format_note_content_for_view, recording_link_title_fetches
from app.services.link_icons import LinkIconFetchResult, link_icon_store, normalized_icon_png
from app.services.link_titles import link_title_store

PAPER = "https://arxiv.org/abs/1811.09786"
LABEL = "[1811.09786] Recurrently Controlled Recurrent Networks"
DOMAIN = '<span class="link-title-domain"> · arxiv.org</span>'


def _icon_png_base64() -> str:
    out = BytesIO()
    Image.new("RGBA", (32, 32), "red").save(out, "PNG")
    png = normalized_icon_png(out.getvalue())
    assert png is not None
    return base64.b64encode(png).decode("ascii")


ICON = _icon_png_base64()
ICON_HTML = f'<img class="link-title-icon" src="data:image/png;base64,{ICON}" alt="">'


@pytest.fixture
def links(monkeypatch: pytest.MonkeyPatch):
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
    connection.close()


def _with_icon() -> None:
    link_icon_store.apply_fetch_result(LinkIconFetchResult(
        origin="https://arxiv.org", icon_png_base64=ICON, status="ok", last_error_kind=None))


def _with_title(connection: sqlite3.Connection, url: str, title: str) -> None:
    now = datetime.now(timezone.utc)
    insert_link_title_row(
        connection, url=url, url_encryption_nonce=None, url_encryption_tag=None, title=title,
        title_encryption_nonce=None, title_encryption_tag=None, status="ok", last_error_kind=None,
        last_checked_at=now, last_success_at=now, last_failure_at=None, next_check_after=None,
        failure_count=0, created_at=now, updated_at=now,
    )
    link_title_store.bootstrap(connection=connection)


def _rendered(html: str, tags: str) -> str:
    return format_note_content_for_view(content_html=html, tags=tags, redact_credentials=False)


def _decorated(text: str) -> str:
    return (f'<a class="link-title" href="{PAPER}" target="_blank" rel="noopener noreferrer">'
            f'{ICON_HTML}{text}{DOMAIN}</a>')


# 1, 2: a link with its own text, alone on its line or in a sentence.
def test_a_link_with_its_own_text_gets_the_icon_and_the_domain(links) -> None:
    _with_icon()

    assert _decorated(LABEL) in _rendered(f'<div><a href="{PAPER}">{LABEL}</a></div>', "")


def test_a_link_with_its_own_text_in_a_sentence_too(links) -> None:
    _with_icon()

    rendered = _rendered(f'<div>Read <a href="{PAPER}">this paper</a> first.</div>', "")

    assert f"Read {_decorated('this paper')} first." in rendered


# 3, 4: a bare address gets its fetched title, in a sentence too.
def test_a_bare_address_in_a_sentence_gets_its_fetched_title(links) -> None:
    _with_title(links, PAPER, LABEL)
    _with_icon()

    rendered = _rendered(f"<div>Idea: this paper {PAPER} indicates that</div>", "")

    assert (f'Idea: this paper <a class="link-title" href="{PAPER}" title="{PAPER}" target="_blank" '
            f'rel="noopener noreferrer">{ICON_HTML}<span class="link-title-text">{LABEL}</span>{DOMAIN}</a> '
            "indicates that") in rendered


def test_a_bare_address_in_a_sentence_shows_the_address_until_its_title_arrives(links, monkeypatch) -> None:
    requested: list[str] = []
    monkeypatch.setattr(link_title_store, "maybe_enqueue_fetch", requested.append)

    rendered = _rendered(f"<div>Idea: this paper {PAPER} indicates that</div>", "")

    assert f'<a href="{PAPER}" target="_blank" rel="noopener noreferrer">{PAPER}</a> indicates' in rendered
    assert requested == [PAPER]


# 5: a Markdown link.
def test_a_markdown_link_gets_the_icon_and_the_domain(links) -> None:
    _with_icon()

    rendered = _rendered(f"<div>See [the paper]({PAPER}) here</div>", "@markdown")

    assert ICON_HTML in rendered
    assert f"the paper{DOMAIN}</a>" in rendered


# 6: not a web page.
@pytest.mark.parametrize("html", [
    '<div><a href="mailto:someone@example.com">Write to me</a></div>',
    '<div><a href="#section">Jump</a></div>',
])
def test_links_that_are_not_web_pages_stay_as_they_are(links, html) -> None:
    rendered = _rendered(html, "")

    assert "link-title" not in rendered


def test_a_linked_picture_stays_as_it_is(links) -> None:
    _with_icon()

    rendered = _rendered(f'<div><a href="{PAPER}"><img src="data:image/png;base64,{ICON}" alt="figure"></a></div>', "")

    assert "link-title" not in rendered


# 7: a site without an icon: text and domain, and its icon is asked for (never its title).
def test_a_site_without_an_icon_yet_shows_text_and_domain_and_asks_for_the_icon(links, monkeypatch) -> None:
    icons: list[str] = []
    titles: list[str] = []
    monkeypatch.setattr(link_icon_store, "maybe_enqueue_fetch", icons.append)
    monkeypatch.setattr(link_title_store, "maybe_enqueue_fetch", titles.append)

    rendered = _rendered(f'<div><a href="{PAPER}">{LABEL}</a></div>', "")

    assert (f'<a class="link-title" href="{PAPER}" target="_blank" rel="noopener noreferrer">'
            f"{LABEL}{DOMAIN}</a>") in rendered
    assert icons == [PAPER]
    assert titles == []


def test_a_cached_render_asks_again_for_the_icon_only(links, monkeypatch) -> None:
    with recording_link_title_fetches() as recorded:
        _rendered(f'<div><a href="{PAPER}">{LABEL}</a></div>', "")
    icons: list[str] = []
    titles: list[str] = []
    monkeypatch.setattr(link_icon_store, "maybe_enqueue_fetch", icons.append)
    monkeypatch.setattr(link_title_store, "maybe_enqueue_fetch", titles.append)

    content_formatting.replay_link_title_fetches(tuple(recorded))

    assert (icons, titles) == ([PAPER], [])


# 11: text that already is the domain.
@pytest.mark.parametrize("text", ["arxiv.org", "www.arxiv.org", "ARXIV.ORG"])
def test_text_that_is_the_domain_is_not_followed_by_it_again(links, text) -> None:
    _with_icon()

    rendered = _rendered(f'<div><a href="{PAPER}">{text}</a></div>', "")

    assert ICON_HTML in rendered
    assert "link-title-domain" not in rendered
