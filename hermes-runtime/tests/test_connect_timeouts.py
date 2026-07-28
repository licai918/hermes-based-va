"""Every connection this codebase opens must bound its TCP connect.

WHY. `psycopg.connect` has no default `connect_timeout`, so a Postgres that is
UNREACHABLE WITHOUT REFUSING -- a dropped network, a firewall that blackholes, a
host up but not listening -- blocks until the OS gives up, which on Linux is well
over a minute. A host that actively REFUSES fails in milliseconds, which is why
this never shows up in development: the local database either answers or refuses.

Every fail-open path in this codebase is written as though failure is fast.
`emit_metric_event` is the sharpest case -- its docstring promises it "must never
fail a turn", and it reasoned explicitly about a pool's bounded 30s wait being
too much of a stall, then opened an unpooled connection with no timeout at all,
which is unbounded. Fail-open only works if the failure is bounded.

TEST-NET-1 (RFC 5737 192.0.2.0/24) is reserved for documentation and is
guaranteed not to route, which makes it the closest thing to a blackholing host
that a test can rely on.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest

from hermes_runtime.datastore.config import (
    CONNECT_TIMEOUT_OFFLINE_SECONDS,
    CONNECT_TIMEOUT_TURN_SECONDS,
)

# Guaranteed-unroutable by RFC 5737. Port is irrelevant; nothing answers.
_BLACKHOLE_DSN = "postgresql://toee:toee@192.0.2.1:5432/toee_va"

# Generous enough that a slow machine does not flake, tight enough that an
# UNBOUNDED connect (tens of seconds at minimum) cannot pass.
_BUDGET_SECONDS = 8.0

_RUNTIME_PKG = Path(__file__).resolve().parents[1] / "hermes_runtime"


def test_the_turn_path_metric_emit_returns_promptly_when_the_host_blackholes(
    monkeypatch,
) -> None:
    """The guarantee is boundedness, so the assertion is on elapsed time."""
    from hermes_runtime import metrics

    monkeypatch.setattr(metrics, "database_url", lambda: _BLACKHOLE_DSN)

    started = time.monotonic()
    metrics.emit_metric_event(metrics.MEMORY_INJECTION, True)  # must not raise
    elapsed = time.monotonic() - started

    assert elapsed < _BUDGET_SECONDS, (
        f"emit_metric_event took {elapsed:.1f}s against an unroutable host. It is "
        "on the path that produces a customer reply, and the reply waits behind "
        "it. Check that connect_timeout is still being passed."
    )


def test_the_failed_emit_is_still_recorded_rather_than_silently_dropped(
    monkeypatch, caplog
) -> None:
    """A timeout that silently drops metrics is a different bug wearing the fix's clothes.

    Bounding the failure must not also hide it: the emit still logs, by exception
    type only (no DSN, no credentials, no customer value).
    """
    from hermes_runtime import metrics

    monkeypatch.setattr(metrics, "database_url", lambda: _BLACKHOLE_DSN)

    with caplog.at_level("WARNING", logger="hermes_runtime.metrics"):
        metrics.emit_metric_event(metrics.KNOWLEDGE_SEARCH, False)

    assert any(
        "metric emit failed" in record.getMessage() for record in caplog.records
    ), "a bounded failure must still be visible; silence would hide an outage"


@pytest.mark.parametrize(
    "relative_path",
    [
        "metrics.py",
        "integration_probe.py",
        "datastore/migrate.py",
        "datastore/pool.py",
        "knowledge/ingest.py",
        "knowledge/migrate.py",
    ],
)
def test_every_connect_site_bounds_its_tcp_connect(relative_path: str) -> None:
    """A completeness check, so the next unbounded connect cannot arrive quietly.

    Source-level rather than behavioural: several of these are migration and
    ingestion entry points that a unit test cannot reasonably drive, and the
    property -- "this call names a connect timeout" -- is exactly what the source
    shows. It is deliberately NOT a count: a count passes when someone adds a
    seventh site and updates the number.
    """
    source = (_RUNTIME_PKG / relative_path).read_text(encoding="utf-8")

    # `psycopg.connect(` in the runtime package, or the pool's own construction.
    connects = len(re.findall(r"psycopg\.connect\s*\(", source))
    pools = len(re.findall(r"ConnectionPool\s*\(", source))
    assert connects + pools > 0, (
        f"{relative_path} no longer opens a connection -- if that is deliberate, "
        "drop it from this parametrize list rather than leaving a vacuous case."
    )

    timeouts = len(re.findall(r"connect_timeout", source))
    assert timeouts >= connects + pools, (
        f"{relative_path} opens {connects + pools} connection(s) but names "
        f"connect_timeout {timeouts} time(s). An unbounded connect turns every "
        "fail-open path downstream of it into a hang."
    )


def test_the_two_budgets_are_ordered_and_short_enough_to_matter() -> None:
    """Pins the intent, not just the numbers.

    The turn-path budget exists to be shorter than a person notices; the offline
    one exists to be bounded at all. If someone raises the turn budget to a value
    that would be felt in a reply, that is a decision worth stopping on.
    """
    assert CONNECT_TIMEOUT_TURN_SECONDS < CONNECT_TIMEOUT_OFFLINE_SECONDS
    assert CONNECT_TIMEOUT_TURN_SECONDS <= 3, (
        "the turn-path connect budget is now long enough for a customer to feel; "
        "NFR-5 says memory and metrics must never stall a reply"
    )
