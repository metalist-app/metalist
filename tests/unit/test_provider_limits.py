"""Batches go out as fast as the provider's own limits allow, and a refused or overloaded
request waits and goes again (app/services/agent/provider_limits.py). Until 2026-11-07
every summary and tagging run sent at most 4 batches at a time, and one 429 failed the
whole run."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.services.agent import provider_limits
from app.services.agent.provider_limits import (
    RateLimitGate,
    RateLimitedTransport,
    SavedLimits,
    gate_for,
    limits_from_headers,
)

BASE_URL = "https://api.example.test/v1/"
MODEL = "model-a"


@pytest.fixture(autouse=True)
def fresh_limits(monkeypatch):
    monkeypatch.setattr(provider_limits, "_GATES", {})
    sleeps: list[float] = []

    async def no_wait(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(provider_limits, "_pause", no_wait)
    return sleeps


def _openai_headers(*, requests: int, tokens: int) -> dict[str, str]:
    return {
        "x-ratelimit-limit-requests": "30000", "x-ratelimit-remaining-requests": str(requests),
        "x-ratelimit-reset-requests": "2ms",
        "x-ratelimit-limit-tokens": "180000000", "x-ratelimit-remaining-tokens": str(tokens),
        "x-ratelimit-reset-tokens": "6m0s",
    }


def test_openai_limits_are_read_from_its_headers() -> None:
    limits = limits_from_headers(httpx.Headers(_openai_headers(requests=29_999, tokens=179_999_835)), now=100.0)
    assert limits.remaining_requests == 29_999
    assert limits.remaining_tokens == 179_999_835
    assert limits.requests_reset_at == pytest.approx(100.002)
    assert limits.tokens_reset_at == pytest.approx(460.0)


def test_anthropic_limits_are_read_from_its_headers() -> None:
    headers = httpx.Headers({
        "anthropic-ratelimit-requests-limit": "4000", "anthropic-ratelimit-requests-remaining": "3999",
        "anthropic-ratelimit-requests-reset": "2026-11-07T20:00:30Z",
        "anthropic-ratelimit-tokens-limit": "2000000", "anthropic-ratelimit-tokens-remaining": "1990000",
        "anthropic-ratelimit-tokens-reset": "2026-11-07T20:01:00Z",
        "date": "Sat, 07 Nov 2026 20:00:00 GMT",
    })
    limits = limits_from_headers(headers, now=50.0)
    assert (limits.remaining_requests, limits.remaining_tokens) == (3999, 1_990_000)
    assert limits.requests_reset_at == pytest.approx(80.0)
    assert limits.tokens_reset_at == pytest.approx(110.0)


def test_a_provider_without_limit_headers_has_no_reading() -> None:
    assert limits_from_headers(httpx.Headers({"content-type": "application/json"}), now=1.0) is None


def _transport(answers: list[httpx.Response]) -> tuple[RateLimitedTransport, list[httpx.Request]]:
    sent: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return answers[len(sent) - 1]

    return RateLimitedTransport(inner=httpx.MockTransport(answer), base_url=BASE_URL, model=MODEL), sent


async def _post(transport: RateLimitedTransport) -> httpx.Response:
    async with httpx.AsyncClient(transport=transport) as client:
        return await client.post(BASE_URL + "responses", json={"input": "hello"})


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504, 529])
def test_a_refused_or_overloaded_request_waits_as_told_and_goes_again(fresh_limits, status: int) -> None:
    transport, sent = _transport([
        httpx.Response(status, headers={"retry-after": "7"}),
        httpx.Response(200, headers=_openai_headers(requests=10, tokens=10_000), json={"ok": True}),
    ])
    response = asyncio.run(_post(transport))
    assert response.status_code == 200
    assert len(sent) == 2
    assert sent[1].content == sent[0].content
    assert fresh_limits == [7.0]


def test_a_request_the_provider_rejects_is_not_sent_again(fresh_limits) -> None:
    transport, sent = _transport([httpx.Response(400, json={"error": "bad request"})])
    assert asyncio.run(_post(transport)).status_code == 400
    assert len(sent) == 1
    assert fresh_limits == []


def test_retries_stop_after_the_limit_and_the_provider_answer_stands(fresh_limits) -> None:
    attempts = provider_limits.MAX_RETRIES + 1
    transport, sent = _transport([httpx.Response(429, headers={"retry-after": "1"})] * attempts)
    assert asyncio.run(_post(transport)).status_code == 429
    assert len(sent) == attempts


def test_without_retry_after_the_wait_grows(fresh_limits) -> None:
    transport, _sent = _transport([httpx.Response(503)] * 3 + [httpx.Response(200)])
    asyncio.run(_post(transport))
    assert fresh_limits == sorted(fresh_limits) and len(set(fresh_limits)) == 3


def test_every_answer_updates_the_limits_its_batches_share() -> None:
    transport, _sent = _transport([httpx.Response(200, headers=_openai_headers(requests=500, tokens=3_000_000))])
    asyncio.run(_post(transport))
    gate = gate_for(base_url=BASE_URL, model=MODEL)
    assert gate.limits is not None and gate.limits.remaining_tokens == 3_000_000


def test_with_room_in_the_limits_every_batch_goes_out_at_once() -> None:
    # 36 batches of 500,000 tokens, as a 100,000-note summary, against 180 million tokens a minute.
    gate = gate_for(base_url=BASE_URL, model=MODEL)
    gate.record(limits_from_headers(httpx.Headers(_openai_headers(requests=30_000, tokens=180_000_000)), now=time.monotonic()))
    assert _most_at_once(gate, batches=36, tokens=500_000) == 36


def test_until_the_limits_are_known_four_go_out_at_once() -> None:
    gate = gate_for(base_url=BASE_URL, model=MODEL)
    assert _most_at_once(gate, batches=12, tokens=1_000) == provider_limits.UNKNOWN_LIMITS_CONCURRENCY == 4


def test_tight_token_limits_hold_batches_back() -> None:
    gate = gate_for(base_url=BASE_URL, model=MODEL)
    gate.record(limits_from_headers(httpx.Headers(_openai_headers(requests=30_000, tokens=1_000_000)), now=time.monotonic()))
    assert _most_at_once(gate, batches=10, tokens=300_000) == 3


def test_a_batch_larger_than_what_remains_still_goes_alone() -> None:
    # The provider answers it, or refuses it and the transport waits; it never waits forever here.
    gate = gate_for(base_url=BASE_URL, model=MODEL)
    gate.record(limits_from_headers(httpx.Headers(_openai_headers(requests=30_000, tokens=1_000)), now=time.monotonic()))
    assert _most_at_once(gate, batches=2, tokens=500_000) == 1


def _most_at_once(gate: RateLimitGate, *, batches: int, tokens: int) -> int:
    in_flight = 0
    most = 0

    async def batch() -> None:
        nonlocal in_flight, most
        async with gate.slot(tokens):
            in_flight += 1
            most = max(most, in_flight)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            in_flight -= 1

    async def run_all() -> None:
        await asyncio.gather(*(batch() for _ in range(batches)))

    asyncio.run(run_all())
    return most


# Each model's limits are saved in the vault (the maintainer, 2026-11-08): after a restart its
# batches go out as the saved limits allow, not four at once until a first answer reports them.
def test_saved_limits_let_every_batch_go_at_once_after_a_restart(saved_rate_limits) -> None:
    saved_rate_limits.saved[(BASE_URL, MODEL)] = SavedLimits(request_limit=30_000, token_limit=180_000_000)
    gate = gate_for(base_url=BASE_URL, model=MODEL)
    assert _most_at_once(gate, batches=36, tokens=500_000) == 36


def test_another_model_has_its_own_saved_limits(saved_rate_limits) -> None:
    saved_rate_limits.saved[(BASE_URL, "model-b")] = SavedLimits(request_limit=30_000, token_limit=180_000_000)
    gate = gate_for(base_url=BASE_URL, model=MODEL)
    assert _most_at_once(gate, batches=12, tokens=1_000) == provider_limits.UNKNOWN_LIMITS_CONCURRENCY


def test_an_answer_saves_the_limits_only_when_they_change(saved_rate_limits) -> None:
    changed = {**_openai_headers(requests=29_000, tokens=170_000_000), "x-ratelimit-limit-tokens": "30000000"}
    transport, _sent = _transport([
        httpx.Response(200, headers=_openai_headers(requests=29_999, tokens=179_000_000)),
        httpx.Response(200, headers=_openai_headers(requests=29_998, tokens=178_000_000)),
        httpx.Response(200, headers=changed),
    ])

    async def three_requests() -> None:
        for _ in range(3):
            await _post(transport)

    asyncio.run(three_requests())
    # What is left changes with every answer; only the account's limits are saved, once each.
    assert saved_rate_limits.saves == [
        ((BASE_URL, MODEL), SavedLimits(request_limit=30_000, token_limit=180_000_000)),
        ((BASE_URL, MODEL), SavedLimits(request_limit=30_000, token_limit=30_000_000)),
    ]


def test_limits_already_saved_are_not_saved_again(saved_rate_limits) -> None:
    saved_rate_limits.saved[(BASE_URL, MODEL)] = SavedLimits(request_limit=30_000, token_limit=180_000_000)
    transport, _sent = _transport([httpx.Response(200, headers=_openai_headers(requests=29_999, tokens=179_000_000))])
    asyncio.run(_post(transport))
    assert saved_rate_limits.saves == []
