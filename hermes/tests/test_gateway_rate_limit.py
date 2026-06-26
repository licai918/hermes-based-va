"""Per-phone soft inbound rate limiter tests (ADR-0109).

Ports services/hermes-gateway rate-limit.test.ts: sliding window (default 10/min)
keyed by normalized fromPhone. Blocked attempts are not recorded; the window
slides as time advances; senders are isolated.
"""

from __future__ import annotations

from toee_hermes.gateway.rate_limit import create_inbound_rate_limiter


def test_allows_up_to_limit_then_blocks() -> None:
    limiter = create_inbound_rate_limiter(limit=3, window_ms=1000)
    assert [limiter.check("+1", at_ms=0).allowed for _ in range(3)] == [True, True, True]
    decision = limiter.check("+1", at_ms=0)
    assert decision.allowed is False
    assert decision.count == 3


def test_window_slides() -> None:
    limiter = create_inbound_rate_limiter(limit=2, window_ms=1000)
    assert limiter.check("+1", at_ms=0).allowed is True
    assert limiter.check("+1", at_ms=500).allowed is True
    blocked = limiter.check("+1", at_ms=900)
    assert blocked.allowed is False
    assert blocked.count == 2
    # 0 and 500 both age out by 1600 (>= 1000ms window), so a new hit is allowed.
    assert limiter.check("+1", at_ms=1600).allowed is True


def test_senders_are_isolated() -> None:
    limiter = create_inbound_rate_limiter(limit=1, window_ms=1000)
    assert limiter.check("+1", at_ms=0).allowed is True
    assert limiter.check("+2", at_ms=0).allowed is True
    assert limiter.check("+1", at_ms=0).allowed is False


def test_default_limit_is_ten_per_minute() -> None:
    limiter = create_inbound_rate_limiter()
    assert all(limiter.check("+1", at_ms=0).allowed for _ in range(10))
    assert limiter.check("+1", at_ms=0).allowed is False
