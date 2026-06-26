"""Per-phone soft inbound rate limiter (ADR-0109).

v1 tracks accepted inbound volume by normalized fromPhone over a sliding window
of ten messages per minute. When a sender exceeds the limit the gateway still
persists the turn and returns 200, but skips async job enqueue; this limiter only
renders the allow/limit decision and the route layer applies that behavior.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

_DEFAULT_LIMIT = 10
_DEFAULT_WINDOW_MS = 60_000


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    count: int  # Count of in-window hits already recorded for the sender.


class InboundRateLimiter:
    def __init__(self, *, limit: int, window_ms: int) -> None:
        self._limit = limit
        self._window_ms = window_ms
        self._hits: dict[str, list[float]] = {}

    def check(self, from_phone: str, at_ms: Optional[float] = None) -> RateLimitDecision:
        now = at_ms if at_ms is not None else time.monotonic() * 1000
        recent = [t for t in self._hits.get(from_phone, []) if now - t < self._window_ms]
        if len(recent) >= self._limit:
            self._hits[from_phone] = recent
            return RateLimitDecision(allowed=False, count=len(recent))
        recent.append(now)
        self._hits[from_phone] = recent
        return RateLimitDecision(allowed=True, count=len(recent))


def create_inbound_rate_limiter(
    *, limit: int = _DEFAULT_LIMIT, window_ms: int = _DEFAULT_WINDOW_MS
) -> InboundRateLimiter:
    return InboundRateLimiter(limit=limit, window_ms=window_ms)
