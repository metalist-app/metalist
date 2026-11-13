from __future__ import annotations

from app.services.login_rate_limit import LoginRateLimiter


def test_rate_limiter_blocks_after_max_attempts(monkeypatch) -> None:
    clock = {"now": 100.0}

    def fake_now() -> float:
        return clock["now"]

    monkeypatch.setattr("app.services.login_rate_limit.time.monotonic", fake_now)

    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60, block_seconds=120)
    key = "ip:127.0.0.1"

    assert limiter.check_allowed(key) == (True, 0)
    limiter.record_failure(key)
    limiter.record_failure(key)
    limiter.record_failure(key)

    allowed, retry_after = limiter.check_allowed(key)
    assert allowed is False
    assert retry_after == 120

    clock["now"] = 221.0
    assert limiter.check_allowed(key) == (True, 0)


def test_rate_limiter_attempt_window_expires(monkeypatch) -> None:
    clock = {"now": 100.0}

    def fake_now() -> float:
        return clock["now"]

    monkeypatch.setattr("app.services.login_rate_limit.time.monotonic", fake_now)

    limiter = LoginRateLimiter(max_attempts=2, window_seconds=60, block_seconds=120)
    key = "ip:127.0.0.1"

    limiter.record_failure(key)
    clock["now"] = 161.0
    limiter.record_failure(key)
    assert limiter.check_allowed(key) == (True, 0)


def test_rate_limiter_success_clears_state(monkeypatch) -> None:
    clock = {"now": 100.0}

    def fake_now() -> float:
        return clock["now"]

    monkeypatch.setattr("app.services.login_rate_limit.time.monotonic", fake_now)

    limiter = LoginRateLimiter(max_attempts=2, window_seconds=60, block_seconds=120)
    key = "ip:127.0.0.1"

    limiter.record_failure(key)
    limiter.record_success(key)
    assert limiter.check_allowed(key) == (True, 0)


def test_rate_limiter_drops_buckets_of_other_ips_past_the_window(monkeypatch) -> None:
    clock = {"now": 100.0}

    def fake_now() -> float:
        return clock["now"]

    monkeypatch.setattr("app.services.login_rate_limit.time.monotonic", fake_now)

    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60, block_seconds=120)
    for index in range(1000):
        limiter.record_failure(f"ip:10.0.{index // 256}.{index % 256}")
    clock["now"] = 150.0
    limiter.record_failure("ip:192.168.1.1")
    clock["now"] = 161.0

    limiter.check_allowed("ip:192.168.1.2")

    assert set(limiter._buckets) == {"ip:192.168.1.1"}


def test_rate_limiter_keeps_a_blocked_bucket_past_the_window(monkeypatch) -> None:
    clock = {"now": 100.0}

    def fake_now() -> float:
        return clock["now"]

    monkeypatch.setattr("app.services.login_rate_limit.time.monotonic", fake_now)

    limiter = LoginRateLimiter(max_attempts=2, window_seconds=60, block_seconds=120)
    blocked = "ip:10.0.0.1"
    limiter.record_failure(blocked)
    limiter.record_failure(blocked)
    clock["now"] = 200.0

    limiter.record_failure("ip:10.0.0.2")

    assert limiter.check_allowed(blocked) == (False, 20)
    clock["now"] = 221.0
    limiter.record_failure("ip:10.0.0.3")
    assert blocked not in limiter._buckets


def test_a_lockout_read_in_the_same_clock_tick_says_its_whole_length(monkeypatch) -> None:
    # Windows' clock ticks coarsely, so the check can read the very time the block began. At a
    # reading like this one, (now + 300) - now is 300.0000000001, which rounded up said "Try
    # again in 301 seconds" (Windows CI, 2026-11-12).
    monkeypatch.setattr("app.services.login_rate_limit.time.monotonic", lambda: 1048551.8293619998)
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60, block_seconds=300)
    key = "ip:127.0.0.1"
    for _ in range(3):
        limiter.record_failure(key)

    assert limiter.check_allowed(key) == (False, 300)
