"""Polite per-site pacing of link-title lookups (docs/ui/content-formatting.md):
one request to a site at a time, spaced apart, and none while a site that
answered HTTP 429 (too many requests) is cooling down."""

from datetime import datetime, timedelta, timezone
import threading
import time

import httpx
import pytest

import app.services.link_titles as link_titles
from app.services.link_titles import (
    _HostPacer,
    _LinkTitleFetchResult,
    _ResolvedHttpTarget,
    _next_check_after_for_status,
    _pacing_host,
    _rate_limit_cooldown_seconds,
    fetch_link_title,
)

HTML = b"<html><head><title>A video</title></head></html>"


@pytest.fixture
def pacer(monkeypatch: pytest.MonkeyPatch) -> _HostPacer:
    pacer = _HostPacer()
    monkeypatch.setattr(link_titles, "_host_pacer", pacer)
    monkeypatch.setattr(
        link_titles, "_resolve_public_http_target",
        lambda url: _ResolvedHttpTarget(hostname=_pacing_host(url), port=443, public_addresses=("93.184.216.34",)),
    )
    return pacer


def _serve(monkeypatch: pytest.MonkeyPatch, handler) -> list[str]:
    """Answer title requests with `handler`; returns the URLs requested."""
    requested: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return handler(request)

    monkeypatch.setattr(link_titles, "_PinnedHTTPTransport", lambda **_kwargs: httpx.MockTransport(respond))
    return requested


def test_a_rate_limited_site_is_left_alone_while_other_sites_are_still_asked(monkeypatch, pacer) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.medium.com":
            return httpx.Response(429, headers={"Retry-After": "120"})
        return httpx.Response(200, headers={"content-type": "text/html"}, content=HTML)

    requested = _serve(monkeypatch, handler)
    monkeypatch.setattr(link_titles, "_HOST_REQUEST_SPACING_SECONDS", 0.0)

    first = fetch_link_title("https://www.medium.com/one")
    assert first == _LinkTitleFetchResult(url="https://www.medium.com/one", title=None,
                                          status="failed", last_error_kind="http_429")
    # Another page on the same site (with or without "www.") is not requested.
    assert fetch_link_title("https://medium.com/two").status == "deferred"
    assert fetch_link_title("https://www.medium.com/three").status == "deferred"
    assert fetch_link_title("https://example.com/page").status == "ok"
    assert requested == ["https://www.medium.com/one", "https://example.com/page"]


def test_a_deferred_lookup_records_nothing_and_can_be_asked_again(monkeypatch, pacer) -> None:
    pacer.cool_down("youtube.com", 120)
    discarded: list[str] = []
    applied: list[object] = []
    monkeypatch.setattr(link_titles, "current_generation", lambda: 1)
    monkeypatch.setattr(link_titles.link_title_store, "discard_in_flight", discarded.append)
    monkeypatch.setattr(link_titles.link_title_store, "apply_current_fetch_result",
                        lambda result, generation: applied.append(result))

    link_titles._run_fetch_job("https://www.youtube.com/watch?v=two", 1)

    assert discarded == ["https://www.youtube.com/watch?v=two"]
    assert applied == []


def test_requests_to_one_site_never_overlap_and_are_spaced(monkeypatch, pacer) -> None:
    monkeypatch.setattr(link_titles, "_HOST_REQUEST_SPACING_SECONDS", 0.3)
    in_request = threading.Event()
    starts: list[float] = []
    ends: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert not in_request.is_set(), "two requests to the same site at once"
        in_request.set()
        starts.append(time.monotonic())
        time.sleep(0.05)
        ends.append(time.monotonic())
        in_request.clear()
        return httpx.Response(200, headers={"content-type": "text/html"}, content=HTML)

    _serve(monkeypatch, handler)
    threads = [threading.Thread(target=fetch_link_title, args=(f"https://example.com/{index}",)) for index in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(starts) == 3
    for previous_end, next_start in zip(ends, starts[1:]):
        assert next_start - previous_end >= 0.3


def test_other_sites_are_not_held_up_by_one_site_s_spacing(monkeypatch, pacer) -> None:
    monkeypatch.setattr(link_titles, "_HOST_REQUEST_SPACING_SECONDS", 5.0)
    _serve(monkeypatch, lambda request: httpx.Response(200, headers={"content-type": "text/html"}, content=HTML))
    fetch_link_title("https://example.com/a")

    started = time.monotonic()
    assert fetch_link_title("https://example.net/b").status == "ok"
    assert time.monotonic() - started < 1.0


def test_the_site_s_retry_after_sets_the_pause_within_bounds() -> None:
    assert _rate_limit_cooldown_seconds("120") == 120
    assert _rate_limit_cooldown_seconds(" 900 ") == 900
    assert _rate_limit_cooldown_seconds("5") == 60
    assert _rate_limit_cooldown_seconds("999999") == 6 * 60 * 60
    # No Retry-After, or an HTTP date: ten minutes.
    assert _rate_limit_cooldown_seconds(None) == 10 * 60
    assert _rate_limit_cooldown_seconds("Wed, 21 Oct 2026 07:28:00 GMT") == 10 * 60


def test_a_rate_limited_link_is_retried_more_slowly_than_other_failures() -> None:
    now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)

    def retry_after(failure_count: int, kind: str) -> timedelta:
        return _next_check_after_for_status(status="failed", now=now, failure_count=failure_count,
                                            last_error_kind=kind) - now

    assert [retry_after(count, "http_429") for count in range(1, 7)] == [
        timedelta(minutes=10), timedelta(hours=1), timedelta(hours=6), timedelta(days=1),
        timedelta(days=7), timedelta(days=7),
    ]
    assert retry_after(1, "timeout") == timedelta(minutes=1)


def test_the_pacing_site_ignores_www_and_case() -> None:
    assert _pacing_host("https://WWW.YouTube.com/watch?v=x") == "youtube.com"
    assert _pacing_host("https://m.youtube.com/watch?v=x") == "m.youtube.com"


def test_sites_whose_spacing_and_cooldown_are_over_are_forgotten(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every site ever asked stayed in memory (docs/ready-to-build/unbounded-growth-audit.md, M5)."""
    clock = [1000.0]
    monkeypatch.setattr(link_titles.time, "monotonic", lambda: clock[0])
    pacer = _HostPacer()
    for index in range(1000):
        host = f"site{index}.example"
        assert pacer.acquire(host)
        pacer.release(host)
        pacer.cool_down(host, 60)

    clock[0] += 3600
    assert pacer.acquire("now.example")
    pacer.release("now.example")

    assert set(pacer._next_allowed_at) == {"now.example"}
    assert pacer._cooldown_until == {}


def test_a_site_still_spaced_or_cooling_down_is_remembered(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(link_titles.time, "monotonic", lambda: clock[0])
    pacer = _HostPacer()
    assert pacer.acquire("busy.example")
    pacer.release("busy.example")
    pacer.cool_down("slow.example", 600)

    assert pacer.acquire("other.example")
    pacer.release("other.example")

    assert not pacer.acquire("slow.example")
    assert "busy.example" in pacer._next_allowed_at
