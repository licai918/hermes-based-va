"""Unit tests for the Customer Memory retention class-window logic (0.0.3 S28,
FR-30, ADR-0004/0116).

Exercises :func:`is_aged`/:func:`retention_threshold` directly (pure, no DB, no
driver) -- the SAME window math the Postgres sweep handler
(``hermes_runtime.datastore.handlers.retention``) uses to build its DELETE
threshold parameters, so this proves the actual aging decision, not a parallel
reimplementation of it.
"""

from datetime import datetime, timedelta, timezone

from toee_hermes.drivers.mock.retention import (
    PROVISIONAL_RETENTION_DAYS,
    VERIFIED_RETENTION_DAYS,
    is_aged,
    retention_threshold,
)

NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)


def test_provisional_window_is_shorter_than_verified_window() -> None:
    # S28 acceptance: "aged provisional rows selected, verified rows inside
    # their window retained" only makes sense if provisional < verified.
    assert PROVISIONAL_RETENTION_DAYS < VERIFIED_RETENTION_DAYS
    assert VERIFIED_RETENTION_DAYS == 730  # ADR-0116, non-negotiable.


def test_aged_provisional_row_is_selected() -> None:
    last_interaction_at = NOW - timedelta(days=PROVISIONAL_RETENTION_DAYS + 1)
    assert is_aged("provisional", last_interaction_at, NOW) is True


def test_verified_row_inside_its_window_is_retained() -> None:
    # Older than the provisional window but well inside the verified one --
    # must NOT be treated as aged (proves the per-class window, not a single
    # global cutoff).
    last_interaction_at = NOW - timedelta(days=PROVISIONAL_RETENTION_DAYS + 1)
    assert is_aged("verified", last_interaction_at, NOW) is False


def test_verified_row_past_its_window_is_aged() -> None:
    last_interaction_at = NOW - timedelta(days=VERIFIED_RETENTION_DAYS + 1)
    assert is_aged("verified", last_interaction_at, NOW) is True


def test_recently_refreshed_row_is_retained_regardless_of_class() -> None:
    # ADR-0116: "any new inbound or outbound service interaction refreshes the
    # retention window" -- a row touched moments ago is never aged, verified
    # or provisional.
    last_interaction_at = NOW - timedelta(minutes=5)
    assert is_aged("verified", last_interaction_at, NOW) is False
    assert is_aged("provisional", last_interaction_at, NOW) is False


def test_row_exactly_at_the_threshold_is_retained_not_aged() -> None:
    # Strict "<" in is_aged/the SQL WHERE -- a row exactly on the boundary is
    # retained, never a fencepost over-deletion.
    threshold = retention_threshold("provisional", NOW)
    assert is_aged("provisional", threshold, NOW) is False


def test_unknown_binding_kind_falls_back_to_the_longer_safer_window() -> None:
    # No over-deletion for an unclassified/future binding_kind: default to the
    # conservative (longer) verified window rather than the shorter one.
    last_interaction_at = NOW - timedelta(days=PROVISIONAL_RETENTION_DAYS + 1)
    assert is_aged("mystery_kind", last_interaction_at, NOW) is False
