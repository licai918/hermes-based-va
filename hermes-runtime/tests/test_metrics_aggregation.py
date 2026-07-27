"""Pure metric-computation unit tests on fixture data (0.0.3 S26, FR-28 layer ①).

No DB: ``_rate``/``_distribution_dict`` are the pure arithmetic the aggregate
metrics handler layers real SQL rows onto (``datastore/handlers/metrics.py``).
Kept here (not import-cycled into the handler test) so the acceptance's "unit
-- metric computations correct on fixture data" is a fast, DB-free check.
"""

from __future__ import annotations

from hermes_runtime.datastore.handlers._common import (
    METRIC_L6_CONFIRMED,
    METRIC_SELF_SERVICE_USAGE,
    insert_metric_event,
)
from hermes_runtime.datastore.handlers.metrics import _distribution_dict, _rate
from toee_hermes.drivers.mock.metrics import create_metrics_mock_handlers
from toee_hermes.tool_gate import ToolExecutionContext


def test_rate_is_none_for_zero_total() -> None:
    assert _rate(0, 0) is None


def test_rate_divides_hits_by_total() -> None:
    assert _rate(3, 4) == 0.75


def test_rate_is_zero_when_no_hits() -> None:
    assert _rate(0, 5) == 0.0


def test_distribution_dict_defaults_every_slot_count_to_zero() -> None:
    assert _distribution_dict([]) == {"1": 0, "2": 0, "3": 0, "4": 0}


def test_distribution_dict_fills_in_seeded_counts() -> None:
    rows = [(1, 5), (2, 3), (4, 1)]
    assert _distribution_dict(rows) == {"1": 5, "2": 3, "3": 0, "4": 1}


def test_distribution_dict_ignores_an_out_of_range_populated_count() -> None:
    # Defensive: customer_memory_slot's UNIQUE(binding_key, slot_name) caps a
    # binding at the 4 v1 slots, so a >4 row should never occur -- but a
    # pure-function test still pins this doesn't blow up or corrupt the shape.
    rows = [(1, 2), (5, 99)]
    assert _distribution_dict(rows) == {"1": 2, "2": 0, "3": 0, "4": 0}


# --- S21/FR-30: real governed-action counters, no DB ------------------------


class _FakeCursor:
    def __init__(self, calls: list[tuple[str, tuple]]) -> None:
        self._calls = calls

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple) -> None:
        self._calls.append((sql, params))


class _FakeConn:
    """Only a cursor() -- no connect(), no commit(): the driver owns those."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.calls)


def test_insert_metric_event_inserts_one_row_on_the_caller_connection() -> None:
    # Rides the caller's (pooled) connection -- one INSERT, no extra connect,
    # no commit of its own (the driver's execute commits atomically).
    conn = _FakeConn()
    insert_metric_event(conn, metric=METRIC_SELF_SERVICE_USAGE)

    assert len(conn.calls) == 1
    sql, params = conn.calls[0]
    assert "INSERT INTO metric_event" in sql
    assert params[1] == METRIC_SELF_SERVICE_USAGE
    assert params[2] is True


def test_mock_metrics_has_no_proxy_flag_for_the_two_deproxied_tiles() -> None:
    # Grep-proof, DB-free: the two S21 tiles are plain ints on the mock twin
    # too -- no `proxy` wrapper, no proxy label anywhere in the payload.
    handler = create_metrics_mock_handlers()["toee_metrics"]["get_aggregate_metrics"]
    data = handler({}, ToolExecutionContext(profile="internal_copilot"))

    assert data["self_service_usage"] == 0
    assert data["l6_confirmed_entries"] == 0
    assert "proxy" not in repr(data).lower()
    assert METRIC_L6_CONFIRMED == "l6_confirmed_entries"
