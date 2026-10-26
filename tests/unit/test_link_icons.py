"""Site icons beside fetched link titles (docs/ui/content-formatting.md, Link icons; agreed
case by case 2026-10-25). Once per site (origin) the server reads the icon the site's
front page declares (a small one first, the apple-touch-icon after), else /favicon.ico;
the sites whose titles come from oEmbed go straight to /favicon.ico. SVG is refused; an
icon must be a small, decodable image (ICO included) and is stored as one 32-pixel PNG,
encrypted like the titles. A site without an icon is asked again after 1, 7, then every
30 days; nothing about it is shown."""

from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from io import BytesIO
import random
import sqlite3

import httpx
from PIL import Image
import pytest

import app.services.link_icons as link_icons
import app.services.link_titles as link_titles
from app.db.link_icons_sql import fetch_all_link_icon_rows
from app.db.link_titles_sql import insert_link_title_row
from app.db.schema import initialize_schema
from app.services.content_formatting import format_note_content_for_view
from app.security.encryption import clear_encryption_key, get_encryption_service, set_session_dek
from app.services.link_icons import (
    ICON_PIXELS,
    LinkIconFetchResult,
    fetch_link_icon,
    icon_origin_for_url,
    link_icon_store,
    normalized_icon_png,
    rewrite_persisted_link_icons,
)
from app.services.link_titles import _HostPacer, _pacing_host, _ResolvedHttpTarget, link_title_store

SITE = "https://example.com"


def _image(size: tuple[int, int], image_format: str, *, color: str) -> bytes:
    out = BytesIO()
    Image.new("RGBA", size, color).save(out, image_format)
    return out.getvalue()


def _png(size: tuple[int, int]) -> bytes:
    return _image(size, "PNG", color="red")


def _ico() -> bytes:
    out = BytesIO()
    Image.new("RGBA", (64, 64), "blue").save(out, "ICO", sizes=[(16, 16), (32, 32), (64, 64)])
    return out.getvalue()


def _page(head: str) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/html"}, content=f"<html><head>{head}</head></html>".encode())


def _icon(content: bytes, content_type: str) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": content_type}, content=content)


def _decoded(result: LinkIconFetchResult) -> Image.Image:
    assert result.icon_png_base64 is not None
    return Image.open(BytesIO(base64.b64decode(result.icon_png_base64)))


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch):
    """Serve requests from `routes` (exact URL -> response, else 404); records what was requested."""
    monkeypatch.setattr(link_titles, "_host_pacer", _HostPacer())
    monkeypatch.setattr(link_titles, "_HOST_REQUEST_SPACING_SECONDS", 0.0)
    monkeypatch.setattr(
        link_icons, "_resolve_public_http_target",
        lambda url: _ResolvedHttpTarget(hostname=_pacing_host(url), port=443, public_addresses=("93.184.216.34",)),
    )
    routes: dict[str, httpx.Response] = {}
    requested: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested.append(url)
        if url in routes:
            return routes[url]
        return httpx.Response(404)

    monkeypatch.setattr(link_icons, "_PinnedHTTPTransport", lambda **_kwargs: httpx.MockTransport(respond))
    return routes, requested


@pytest.fixture
def icon_database(monkeypatch: pytest.MonkeyPatch):
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


# Fetching


def test_the_small_declared_icon_comes_first(network) -> None:
    routes, requested = network
    routes[f"{SITE}/"] = _page(
        '<link rel="icon" href="/big.png" sizes="192x192">'
        '<link rel="icon" href="/small.png" sizes="32x32">'
        '<link rel="apple-touch-icon" href="/touch.png">'
    )
    routes[f"{SITE}/small.png"] = _icon(_png((32, 32)), "image/png")

    result = fetch_link_icon(SITE)

    assert result.status == "ok"
    assert _decoded(result).size == (ICON_PIXELS, ICON_PIXELS)
    assert requested == [f"{SITE}/", f"{SITE}/small.png"]


def test_the_apple_touch_icon_comes_after_the_declared_icons(network) -> None:
    routes, requested = network
    routes[f"{SITE}/"] = _page('<link rel="apple-touch-icon" href="/touch.png"><link rel="icon" href="/gone.png">')
    routes[f"{SITE}/touch.png"] = _icon(_png((180, 180)), "image/png")

    result = fetch_link_icon(SITE)

    assert result.status == "ok"
    assert requested == [f"{SITE}/", f"{SITE}/gone.png", f"{SITE}/touch.png"]


def test_without_a_declared_icon_the_site_s_favicon_ico_is_used(network) -> None:
    routes, requested = network
    routes[f"{SITE}/"] = _page("<title>No icons here</title>")
    routes[f"{SITE}/favicon.ico"] = _icon(_ico(), "image/x-icon")

    result = fetch_link_icon(SITE)

    assert result.status == "ok"
    assert _decoded(result).size == (ICON_PIXELS, ICON_PIXELS)
    assert requested == [f"{SITE}/", f"{SITE}/favicon.ico"]


def test_icons_are_read_from_where_the_front_page_forwards_to(network) -> None:
    routes, requested = network
    routes[f"{SITE}/"] = httpx.Response(301, headers={"location": "https://www.example.com/"})
    routes["https://www.example.com/"] = _page('<link rel="icon" href="img/fav.png">')
    routes["https://www.example.com/img/fav.png"] = _icon(_png((16, 16)), "image/png")

    assert fetch_link_icon(SITE).status == "ok"
    assert requested[-1] == "https://www.example.com/img/fav.png"


def test_a_site_without_any_icon_has_none(network) -> None:
    routes, requested = network
    routes[f"{SITE}/"] = _page("")

    result = fetch_link_icon(SITE)

    assert result == LinkIconFetchResult(origin=SITE, icon_png_base64=None, status="missing", last_error_kind="http_404")


def test_svg_icons_are_never_requested(network) -> None:
    routes, requested = network
    routes[f"{SITE}/"] = _page(
        '<link rel="icon" href="/icon.svg" sizes="any">'
        '<link rel="icon" href="/vector" type="image/svg+xml">'
    )
    routes[f"{SITE}/favicon.ico"] = _icon(_ico(), "image/x-icon")

    assert fetch_link_icon(SITE).status == "ok"
    assert requested == [f"{SITE}/", f"{SITE}/favicon.ico"]


def test_an_svg_served_as_an_icon_is_refused(network) -> None:
    routes, _requested = network
    routes[f"{SITE}/favicon.ico"] = _icon(b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>', "image/svg+xml")

    assert fetch_link_icon(SITE) == LinkIconFetchResult(
        origin=SITE, icon_png_base64=None, status="missing", last_error_kind="invalid_image")


def test_an_oversized_icon_is_refused(network) -> None:
    routes, _requested = network
    routes[f"{SITE}/favicon.ico"] = _icon(b"\0" * (link_icons._MAX_ICON_BYTES + 1), "image/x-icon")

    assert fetch_link_icon(SITE).last_error_kind == "too_large"


def test_a_page_served_where_the_icon_should_be_is_refused(network) -> None:
    routes, _requested = network
    routes[f"{SITE}/favicon.ico"] = _page("<title>Not found</title>")

    assert fetch_link_icon(SITE).last_error_kind == "invalid_image"


def test_an_icon_that_forwards_to_itself_is_refused(network) -> None:
    routes, _requested = network
    routes[f"{SITE}/favicon.ico"] = httpx.Response(302, headers={"location": f"{SITE}/favicon.ico"})

    assert fetch_link_icon(SITE).last_error_kind == "too_many_redirects"


def test_oembed_sites_go_straight_to_favicon_ico(network) -> None:
    routes, requested = network
    routes["https://www.youtube.com/favicon.ico"] = _icon(_ico(), "image/x-icon")

    assert fetch_link_icon("https://www.youtube.com").status == "ok"
    assert requested == ["https://www.youtube.com/favicon.ico"]


def _noisy_png(size: tuple[int, int]) -> bytes:
    out = BytesIO()
    Image.frombytes("RGB", size, random.Random(size[0]).randbytes(size[0] * size[1] * 3)).save(out, "PNG")
    return out.getvalue()


def test_a_large_declared_icon_is_fetched_and_shrunk(network) -> None:
    # suzyahyah.github.io (2026-10-25): its only icon is a 506-pixel PNG of 454 KB.
    routes, _requested = network
    icon = _noisy_png((506, 506))
    assert len(icon) > 256 * 1024
    routes[f"{SITE}/"] = _page('<link rel="icon" type="image/png" href="/assets/logo.png">')
    routes[f"{SITE}/assets/logo.png"] = _icon(icon, "image/png")

    result = fetch_link_icon(SITE)

    assert result.status == "ok"
    assert _decoded(result).size == (ICON_PIXELS, ICON_PIXELS)


def test_the_light_theme_icon_comes_before_the_dark_theme_one(network) -> None:
    # hashcloak.com (2026-10-25) declares one icon per colour scheme. MetaList's dark theme puts
    # icons on a light tile, so the light one suits both.
    routes, requested = network
    routes[f"{SITE}/"] = _page(
        '<link href="/dark.png" rel="icon" media="(prefers-color-scheme: dark)">'
        '<link rel="apple-touch-icon" href="/touch.png">'
        '<link href="/light.png" rel="icon" media="(prefers-color-scheme: light)">'
    )
    routes[f"{SITE}/light.png"] = _icon(_png((32, 32)), "image/png")

    assert fetch_link_icon(SITE).status == "ok"
    assert requested == [f"{SITE}/", f"{SITE}/light.png"]


def test_a_dark_theme_icon_is_used_when_nothing_else_works(network) -> None:
    routes, requested = network
    routes[f"{SITE}/"] = _page(
        '<link href="/dark.png" rel="icon" media="(prefers-color-scheme:dark)">'
        '<link rel="apple-touch-icon" href="/touch.png">'
    )
    routes[f"{SITE}/dark.png"] = _icon(_png((32, 32)), "image/png")

    assert fetch_link_icon(SITE).status == "ok"
    assert requested == [f"{SITE}/", f"{SITE}/touch.png", f"{SITE}/dark.png"]


def test_a_site_without_a_usable_icon_records_why_its_own_icon_failed(network) -> None:
    # Not the 404 of the /favicon.ico tried last, which hid the real cause (2026-10-25).
    routes, _requested = network
    routes[f"{SITE}/"] = _page('<link rel="icon" href="/logo.png">')
    routes[f"{SITE}/logo.png"] = _icon(b"\0" * (link_icons._MAX_ICON_BYTES + 1), "image/png")

    assert fetch_link_icon(SITE).last_error_kind == "too_large"


def test_a_site_cooling_down_is_asked_later(network) -> None:
    link_titles._host_pacer.cool_down("example.com", 60)

    assert fetch_link_icon(SITE).status == "deferred"


# The stored image


def test_a_wide_icon_is_centred_on_a_square() -> None:
    png = normalized_icon_png(_png((64, 32)))

    assert png is not None
    with Image.open(BytesIO(png)) as image:
        assert image.format == "PNG"
        assert image.size == (ICON_PIXELS, ICON_PIXELS)
        rgba = image.convert("RGBA")
        assert rgba.getpixel((ICON_PIXELS // 2, 0))[3] == 0
        assert rgba.getpixel((ICON_PIXELS // 2, ICON_PIXELS // 2)) == (255, 0, 0, 255)


def _grey(size: tuple[int, int]) -> bytes:
    out = BytesIO()
    Image.new("L", size, 128).save(out, "PNG")
    return out.getvalue()


def test_a_huge_logo_used_as_an_icon_is_shrunk() -> None:
    # hashcloak.com's dark-theme icon (2026-10-25): a 4501-pixel square, 20 million pixels.
    png = normalized_icon_png(_grey((4501, 4501)))

    assert png is not None
    with Image.open(BytesIO(png)) as image:
        assert image.size == (ICON_PIXELS, ICON_PIXELS)


def test_an_image_with_too_many_pixels_is_refused() -> None:
    assert normalized_icon_png(_grey((5001, 5000))) is None


# One site, one icon


def test_one_fetch_per_site(icon_database, monkeypatch: pytest.MonkeyPatch) -> None:
    submitted: list[str] = []
    monkeypatch.setattr(link_icons, "TEST_MODE", False)
    monkeypatch.setattr(link_icons, "_submit_fetch", lambda origin, generation: submitted.append(origin))

    link_icon_store.maybe_enqueue_fetch(f"{SITE}/one")
    link_icon_store.maybe_enqueue_fetch(f"{SITE}/two?x=1")
    link_icon_store.maybe_enqueue_fetch("https://other.example.org/page")

    assert submitted == [SITE, "https://other.example.org"]

    link_icon_store.apply_fetch_result(LinkIconFetchResult(
        origin=SITE, icon_png_base64=base64.b64encode(normalized_icon_png(_png((32, 32)))).decode("ascii"),
        status="ok", last_error_kind=None))
    link_icon_store.maybe_enqueue_fetch(f"{SITE}/three")

    assert submitted == [SITE, "https://other.example.org"]
    assert link_icon_store.get_icon_base64(f"{SITE}/four") is not None


def test_origins_keep_scheme_host_and_port() -> None:
    assert icon_origin_for_url("https://Example.com/a/b?c") == "https://example.com"
    assert icon_origin_for_url("http://example.com:8080/") == "http://example.com:8080"
    assert icon_origin_for_url("https://www.example.com/") == "https://www.example.com"
    assert icon_origin_for_url("ftp://example.com/") is None


@pytest.mark.parametrize(("failures", "days"), [(1, 1), (2, 7), (3, 30), (4, 30)])
def test_a_site_without_an_icon_is_asked_again_after_1_7_then_30_days(icon_database, failures: int, days: int) -> None:
    missing = LinkIconFetchResult(origin=SITE, icon_png_base64=None, status="missing", last_error_kind="http_404")
    for _ in range(failures):
        link_icon_store.apply_fetch_result(missing)

    (row,) = fetch_all_link_icon_rows(icon_database)

    assert row.failure_count == failures
    assert row.next_check_after - row.last_checked_at == timedelta(days=days)
    assert link_icon_store.get_icon_base64(SITE) is None


def test_an_icon_change_refreshes_rendered_links(icon_database) -> None:
    revision = link_title_store.get_revision()
    generation = link_title_store.get_render_generation()

    link_icon_store.apply_fetch_result(LinkIconFetchResult(
        origin=SITE, icon_png_base64=None, status="missing", last_error_kind="http_404"))

    assert link_title_store.get_revision() == revision + 1
    assert link_title_store.get_render_generation() > generation


# Encryption and locking


def _ok_result() -> LinkIconFetchResult:
    png = normalized_icon_png(_png((32, 32)))
    assert png is not None
    return LinkIconFetchResult(
        origin=SITE, icon_png_base64=base64.b64encode(png).decode("ascii"), status="ok", last_error_kind=None)


def test_icons_are_stored_encrypted_and_read_back_after_unlock(icon_database) -> None:
    set_session_dek(b"k" * 32)
    link_title_store.bootstrap(connection=icon_database)
    link_icon_store.apply_fetch_result(_ok_result())

    (row,) = fetch_all_link_icon_rows(icon_database)
    assert row.origin_encryption_nonce is not None and row.icon_png_encryption_nonce is not None
    assert "example.com" not in row.origin
    assert row.icon_png != _ok_result().icon_png_base64

    # Locked: the stored rows stay, nothing is shown.
    clear_encryption_key()
    link_title_store.bootstrap(connection=icon_database)
    assert link_icon_store.get_icon_base64(SITE) is None

    set_session_dek(b"k" * 32)
    link_title_store.ensure_decrypted(token="")
    assert link_icon_store.get_icon_base64(SITE) == _ok_result().icon_png_base64


def test_locking_clears_the_icons(icon_database) -> None:
    link_icon_store.apply_fetch_result(_ok_result())

    link_title_store.reset()

    assert link_icon_store.get_icon_base64(SITE) is None


def test_adding_and_removing_a_password_rewrites_the_icons(icon_database) -> None:
    link_icon_store.apply_fetch_result(_ok_result())
    set_session_dek(b"k" * 32)
    service = get_encryption_service()

    assert rewrite_persisted_link_icons(connection=icon_database, encryption_service=service, force_plaintext=False) == 1
    (row,) = fetch_all_link_icon_rows(icon_database)
    assert row.origin_encryption_nonce is not None and row.icon_png_encryption_nonce is not None

    assert rewrite_persisted_link_icons(connection=icon_database, encryption_service=service, force_plaintext=True) == 1
    (row,) = fetch_all_link_icon_rows(icon_database)
    assert (row.origin, row.origin_encryption_nonce) == (SITE, None)
    assert (row.icon_png, row.icon_png_encryption_nonce) == (_ok_result().icon_png_base64, None)


def test_retry_failed_link_titles_leaves_icons_alone(icon_database) -> None:
    link_icon_store.apply_fetch_result(LinkIconFetchResult(
        origin=SITE, icon_png_base64=None, status="missing", last_error_kind="http_404"))

    assert link_title_store.list_manual_retry_urls() == ()


# Rendering


def _titled(connection: sqlite3.Connection, url: str) -> None:
    now = datetime.now(timezone.utc)
    insert_link_title_row(
        connection, url=url, url_encryption_nonce=None, url_encryption_tag=None, title="An Article",
        title_encryption_nonce=None, title_encryption_tag=None, status="ok", last_error_kind=None,
        last_checked_at=now, last_success_at=now, last_failure_at=None, next_check_after=None,
        failure_count=0, created_at=now, updated_at=now,
    )
    link_title_store.bootstrap(connection=connection)


def _rendered(url: str) -> str:
    return format_note_content_for_view(content_html=f"<div>{url}</div>", tags="", redact_credentials=False)


def test_the_icon_goes_before_the_title(icon_database) -> None:
    _titled(icon_database, f"{SITE}/article")
    link_icon_store.apply_fetch_result(_ok_result())

    assert (
        f'<img class="link-title-icon" src="data:image/png;base64,{_ok_result().icon_png_base64}" alt="">'
        '<span class="link-title-text">An Article</span>'
    ) in _rendered(f"{SITE}/article")


def test_a_title_without_an_icon_yet_shows_alone_and_asks_for_the_icon(icon_database, monkeypatch) -> None:
    submitted: list[str] = []
    monkeypatch.setattr(link_icons, "TEST_MODE", False)
    monkeypatch.setattr(link_icons, "_submit_fetch", lambda origin, generation: submitted.append(origin))
    _titled(icon_database, f"{SITE}/article")

    rendered = _rendered(f"{SITE}/article")

    assert '<a class="link-title"' in rendered
    assert "link-title-icon" not in rendered
    assert submitted == [SITE]


def test_an_icon_without_a_title_shows_nothing(icon_database) -> None:
    link_icon_store.apply_fetch_result(_ok_result())

    rendered = _rendered(f"{SITE}/untitled")

    assert "link-title-icon" not in rendered
    assert f'>{SITE}/untitled</a>' in rendered


def test_a_site_without_an_icon_shows_the_title_alone(icon_database) -> None:
    _titled(icon_database, f"{SITE}/article")
    link_icon_store.apply_fetch_result(LinkIconFetchResult(
        origin=SITE, icon_png_base64=None, status="missing", last_error_kind="http_404"))

    rendered = _rendered(f"{SITE}/article")

    assert "<img" not in rendered
    assert '<span class="link-title-text">An Article</span>' in rendered
