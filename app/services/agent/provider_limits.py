"""A provider's own rate limits decide how many AI batches go out at once, and a request
the provider refuses as too many, or answers as overloaded, waits and goes again.

Until 2026-11-07 a summary or tagging run sent at most 4 batches at a time, a guess at the
smallest accounts' limits, and a single 429 failed the whole run. Now:

- Every answer's rate-limit headers (OpenAI's x-ratelimit-*, Anthropic's
  anthropic-ratelimit-*) are recorded for its endpoint and model (RateLimitedTransport).
- Batches wait for a slot in that endpoint and model's gate (RateLimitGate.slot), which
  admits as many as the remaining requests and tokens allow. Until a first answer has
  told the limits, or for a provider that sends none, UNKNOWN_LIMITS_CONCURRENCY go at once.
- A 429 or an overloaded answer (500, 502, 503, 504, Anthropic's 529) waits the time the
  provider names (retry-after), or a growing pause without one, and the same request goes
  again, up to MAX_RETRIES times; after that the provider's answer stands, as before.
  The waiting happens below the provider SDK, so every request of every batch has it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from http import HTTPStatus
import re
import time

import httpx
import httpx2

# How many batches go at once before the limits are known, or for a provider that sends none:
# the number every run used before 2026-11-07.
UNKNOWN_LIMITS_CONCURRENCY = 4
# Times a refused or overloaded request goes again before the provider's answer stands.
MAX_RETRIES = 6
# Without retry-after, the pause doubles from this: 1, 2, 4, 8, 16 and 32 s.
FIRST_PAUSE_SECONDS = 1.0
PAUSE_GROWTH = 2
# A provider asking for a longer wait gets its refusal back at once: the run fails as before.
LONGEST_PAUSE_SECONDS = 120.0
MS_PER_SECOND = 1000
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
# Anthropic answers 529 when its API is overloaded.
ANTHROPIC_OVERLOADED_STATUS = 529
RETRIED_STATUSES = frozenset({
    HTTPStatus.TOO_MANY_REQUESTS, HTTPStatus.INTERNAL_SERVER_ERROR, HTTPStatus.BAD_GATEWAY,
    HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.GATEWAY_TIMEOUT, ANTHROPIC_OVERLOADED_STATUS,
})
# OpenAI writes its reset times as durations: "6m0s", "1.5s", "2ms", "1h2m3s".
_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
_DURATION_UNIT_SECONDS = {"ms": 1 / MS_PER_SECOND, "s": 1.0, "m": float(SECONDS_PER_MINUTE), "h": float(SECONDS_PER_HOUR)}


@dataclass(frozen=True, slots=True)
class ProviderLimits:
    """One answer's view of the account's limits; reset times on the time.monotonic() clock."""

    request_limit: int
    remaining_requests: int
    requests_reset_at: float
    token_limit: int
    remaining_tokens: int
    tokens_reset_at: float

    def requests_left(self, now: float) -> int:
        if now >= self.requests_reset_at:
            return self.request_limit
        return self.remaining_requests

    def tokens_left(self, now: float) -> int:
        if now >= self.tokens_reset_at:
            return self.token_limit
        return self.remaining_tokens


def _duration_seconds(text: str) -> float:
    parts = _DURATION_PART.findall(text)
    if not parts or "".join(number + unit for number, unit in parts) != text:
        raise ValueError(f"Unreadable rate-limit reset duration: {text!r}")
    return sum(float(number) * _DURATION_UNIT_SECONDS[unit] for number, unit in parts)


def _openai_limits(headers: Mapping[str, str], now: float) -> ProviderLimits:
    return ProviderLimits(
        request_limit=int(headers["x-ratelimit-limit-requests"]),
        remaining_requests=int(headers["x-ratelimit-remaining-requests"]),
        requests_reset_at=now + _duration_seconds(headers["x-ratelimit-reset-requests"]),
        token_limit=int(headers["x-ratelimit-limit-tokens"]),
        remaining_tokens=int(headers["x-ratelimit-remaining-tokens"]),
        tokens_reset_at=now + _duration_seconds(headers["x-ratelimit-reset-tokens"]),
    )


def _anthropic_limits(headers: Mapping[str, str], now: float) -> ProviderLimits:
    # Anthropic writes reset instants (RFC 3339); measured from the answer's own Date, so the
    # server's clock and this computer's need not agree.
    answered_at = parsedate_to_datetime(headers["date"])

    def reset_at(name: str) -> float:
        return now + (datetime.fromisoformat(headers[name]) - answered_at).total_seconds()

    return ProviderLimits(
        request_limit=int(headers["anthropic-ratelimit-requests-limit"]),
        remaining_requests=int(headers["anthropic-ratelimit-requests-remaining"]),
        requests_reset_at=reset_at("anthropic-ratelimit-requests-reset"),
        token_limit=int(headers["anthropic-ratelimit-tokens-limit"]),
        remaining_tokens=int(headers["anthropic-ratelimit-tokens-remaining"]),
        tokens_reset_at=reset_at("anthropic-ratelimit-tokens-reset"),
    )


def limits_from_headers(headers: Mapping[str, str], *, now: float) -> ProviderLimits | None:
    """The limits an answer reports, or None from a provider that reports none (Gemini, local models)."""
    if "x-ratelimit-remaining-tokens" in headers:
        return _openai_limits(headers, now)
    if "anthropic-ratelimit-tokens-remaining" in headers:
        return _anthropic_limits(headers, now)
    return None


def _pause_seconds(headers: Mapping[str, str], retry: int) -> float:
    """How long to wait before sending again: what the provider asks for, else a growing pause."""
    if "retry-after-ms" in headers:
        return float(headers["retry-after-ms"]) / MS_PER_SECOND
    if "retry-after" in headers:
        value = headers["retry-after"]
        if re.fullmatch(r"\d+(?:\.\d+)?", value):
            return float(value)
        # An HTTP date: the wait until then by the answer's own clock.
        return max(0.0, (parsedate_to_datetime(value) - parsedate_to_datetime(headers["date"])).total_seconds())
    return FIRST_PAUSE_SECONDS * PAUSE_GROWTH ** retry


async def _pause(seconds: float) -> None:
    await asyncio.sleep(seconds)


class RateLimitGate:
    """Admits batches for one endpoint and model while its last known limits have room."""

    def __init__(self) -> None:
        self.limits: ProviderLimits | None = None
        self._in_flight = 0
        self._in_flight_tokens = 0
        self._waiters: list[asyncio.Future[None]] = []

    def record(self, limits: ProviderLimits) -> None:
        self.limits = limits
        self._wake()

    def _admits(self, tokens: int, now: float) -> bool:
        # One batch always goes, however large: the provider answers it, or refuses it and
        # the transport waits, so a gate never waits for room that cannot come.
        if self._in_flight == 0:
            return True
        if self.limits is None:
            return self._in_flight < UNKNOWN_LIMITS_CONCURRENCY
        return (self._in_flight < self.limits.requests_left(now)
                and self._in_flight_tokens + tokens <= self.limits.tokens_left(now))

    def _seconds_to_next_reset(self, now: float) -> float | None:
        if self.limits is None:
            return None
        upcoming = [reset_at - now for reset_at in (self.limits.requests_reset_at, self.limits.tokens_reset_at)
                    if reset_at > now]
        if not upcoming:
            return None
        return min(upcoming)

    def _wake(self) -> None:
        for waiter in self._waiters:
            if not waiter.done():
                waiter.set_result(None)
        self._waiters = []

    async def _wait_for_room(self, timeout: float | None) -> None:
        waiter = asyncio.get_running_loop().create_future()
        self._waiters.append(waiter)
        await asyncio.wait({waiter}, timeout=timeout)

    @asynccontextmanager
    async def slot(self, tokens: int) -> AsyncIterator[None]:
        """Hold one of the gate's places for a batch of about `tokens` (input and output) tokens."""
        assert tokens > 0, "A batch has tokens"
        while not self._admits(tokens, time.monotonic()):
            await self._wait_for_room(self._seconds_to_next_reset(time.monotonic()))
        self._in_flight += 1
        self._in_flight_tokens += tokens
        try:
            yield
        finally:
            self._in_flight -= 1
            self._in_flight_tokens -= tokens
            assert self._in_flight >= 0 and self._in_flight_tokens >= 0
            self._wake()


_GATES: dict[tuple[str, str], RateLimitGate] = {}


def gate_for(*, base_url: str, model: str) -> RateLimitGate:
    """The gate every batch to this endpoint and model shares, for as long as MetaList runs."""
    key = (base_url, model)
    if key not in _GATES:
        _GATES[key] = RateLimitGate()
    return _GATES[key]


async def _send_with_retries(inner, request, *, base_url: str, model: str):
    """Send `request` through `inner` (an httpx or httpx2 transport), record the limits each
    answer reports, and send it again while the provider refuses or is overloaded."""
    # Read once, so the same body goes again.
    await request.aread()
    retry = 0
    while True:
        response = await inner.handle_async_request(request)
        limits = limits_from_headers(response.headers, now=time.monotonic())
        if limits is not None:
            gate_for(base_url=base_url, model=model).record(limits)
        if response.status_code not in RETRIED_STATUSES or retry == MAX_RETRIES:
            return response
        seconds = _pause_seconds(response.headers, retry)
        if seconds > LONGEST_PAUSE_SECONDS:
            return response
        await response.aclose()
        await _pause(seconds)
        retry += 1


class RateLimitedTransport(httpx.AsyncBaseTransport):
    """The OpenAI and OpenAI-compatible clients' transport (_send_with_retries)."""

    def __init__(self, *, inner: httpx.AsyncBaseTransport, base_url: str, model: str) -> None:
        self._inner = inner
        self._base_url = base_url
        self._model = model

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await _send_with_retries(self._inner, request, base_url=self._base_url, model=self._model)

    async def aclose(self) -> None:
        await self._inner.aclose()


class Httpx2RateLimitedTransport(httpx2.AsyncBaseTransport):
    """The Anthropic client's transport: its SDK uses httpx2, a separate copy of httpx."""

    def __init__(self, *, inner: httpx2.AsyncBaseTransport, base_url: str, model: str) -> None:
        self._inner = inner
        self._base_url = base_url
        self._model = model

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        return await _send_with_retries(self._inner, request, base_url=self._base_url, model=self._model)

    async def aclose(self) -> None:
        await self._inner.aclose()


def provider_transport(*, base_url: str, model: str) -> RateLimitedTransport:
    """The transport an OpenAI or OpenAI-compatible client sends through: no proxy settings from the environment."""
    return RateLimitedTransport(inner=httpx.AsyncHTTPTransport(trust_env=False), base_url=base_url, model=model)


def anthropic_transport(*, base_url: str, model: str) -> Httpx2RateLimitedTransport:
    """The transport the Anthropic client sends through: no proxy settings from the environment."""
    return Httpx2RateLimitedTransport(inner=httpx2.AsyncHTTPTransport(trust_env=False), base_url=base_url, model=model)
