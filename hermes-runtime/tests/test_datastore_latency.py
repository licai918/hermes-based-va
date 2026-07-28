"""0.0.5 S18 (FR-26): the latency histogram against real Postgres.

Migration 0023 gives ``metric_event`` a nullable ``duration_ms`` so p50/p95 are
arithmetically possible (D5.1 -- the pre-0023 table is ``(id, metric, flag,
created_at)``, over which a percentile cannot be computed at all). These tests
pin the half of S18 that only a real database can prove:

- the percentiles actually come back per layer, from rows;
- a boolean COUNTER row and a latency SAMPLE row can share a metric name
  (``knowledge_search`` does, by design) without contaminating each other;
- a fresh database reports "not yet measured", never a fabricated zero;
- the breach flag is computed against the 150ms line, and only where there is
  data to compute it from;
- the schema refuses a row that carries neither signal.

Skip-if-no-DB via the shared ``datastore`` fixture (a migrated throwaway schema).
"""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import pytest

from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

from hermes_runtime.knowledge.driver import DEFAULT_DEADLINE_MS
from hermes_runtime.latency import (
    LATENCY_L4_LOAD,
    LATENCY_L5_RETRIEVAL,
    LATENCY_L6_LOAD,
    LATENCY_PRE_TURN_TOTAL,
    PRE_TURN_READ_SLO_P95_MS,
    latency_metrics,
)
from hermes_runtime.live import _scripted_openai_factory
from hermes_runtime.openrouter import OpenRouterConfig, make_openrouter_run_turn


def _insert(conn, *, metric: str, flag=None, duration_ms=None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO metric_event (id, metric, flag, duration_ms) VALUES (%s, %s, %s, %s)",
            (f"metric_{uuid.uuid4().hex}", metric, flag, duration_ms),
        )
    conn.commit()


def _tiles(conn) -> dict:
    with conn.cursor() as cur:
        payload = latency_metrics(cur)
    return {tile["metric"]: tile for tile in [payload["total"], *payload["layers"]]}


def test_a_fresh_database_reports_not_measured_rather_than_zero(datastore) -> None:
    _driver, conn, _ = datastore
    tiles = _tiles(conn)

    assert tiles[LATENCY_L4_LOAD]["samples"] == 0
    assert tiles[LATENCY_L4_LOAD]["p95_ms"] is None
    # A zero p95 would render as the best possible latency on a deployment that
    # has never measured anything, and `breached: False` would render green.
    assert tiles[LATENCY_PRE_TURN_TOTAL]["breached"] is None


def test_percentiles_come_back_per_layer_from_real_rows(datastore) -> None:
    _driver, conn, _ = datastore
    for ms in (10.0, 20.0, 30.0):
        _insert(conn, metric=LATENCY_L4_LOAD, duration_ms=ms)
    _insert(conn, metric=LATENCY_L6_LOAD, duration_ms=500.0)

    tiles = _tiles(conn)
    l4 = tiles[LATENCY_L4_LOAD]
    assert l4["samples"] == 3
    assert l4["p50_ms"] == pytest.approx(20.0)
    # percentile_cont interpolates: 0.95 * (3-1) = 1.9 -> 20 + 0.9 * (30-20).
    assert l4["p95_ms"] == pytest.approx(29.0)
    # ... and the other layer is not the same number, i.e. the GROUP BY is real.
    assert tiles[LATENCY_L6_LOAD]["p50_ms"] == pytest.approx(500.0)


def test_a_counter_row_and_a_sample_row_share_a_metric_without_contaminating_it(
    datastore,
) -> None:
    # `knowledge_search` is BOTH: the found/miss counter it has always been, and
    # (since S18) the row that carries L5's retrieval duration. A duration-less
    # counter row must not enter the percentile as a zero, and a timed row must
    # still count in the found/miss rate.
    driver, conn, _ = datastore
    _insert(conn, metric=LATENCY_L5_RETRIEVAL, flag=True, duration_ms=100.0)
    _insert(conn, metric=LATENCY_L5_RETRIEVAL, flag=False, duration_ms=100.0)
    # A pre-0023 style row: boolean only, no duration.
    _insert(conn, metric=LATENCY_L5_RETRIEVAL, flag=True)

    tiles = _tiles(conn)
    assert tiles[LATENCY_L5_RETRIEVAL]["samples"] == 2
    assert tiles[LATENCY_L5_RETRIEVAL]["p50_ms"] == pytest.approx(100.0)

    result = execute_tool(
        tool="toee_metrics",
        action="get_aggregate_metrics",
        params={},
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    )
    assert result.ok, result
    # The counter is unchanged by the new column: all three rows still count.
    assert result.data["knowledge_search"] == {"found": 2, "total": 3, "rate": 0.6667}


def test_the_l5_tile_is_budgeted_against_its_own_deadline_not_the_slo_line(
    datastore,
) -> None:
    # D5.2: L5's shipped budget is 800ms, so a total including it can never meet
    # 150ms. A 400ms retrieval is well inside L5's budget and would be a gross
    # breach of the read SLO -- the tile must judge it against the right line.
    _driver, conn, _ = datastore
    _insert(conn, metric=LATENCY_L5_RETRIEVAL, flag=True, duration_ms=400.0)

    tile = _tiles(conn)[LATENCY_L5_RETRIEVAL]
    assert tile["budget_ms"] == DEFAULT_DEADLINE_MS
    assert tile["breached"] is False
    assert tile["in_slo_total"] is False


def test_the_total_tile_flags_a_breach_against_the_owner_slo_line(datastore) -> None:
    _driver, conn, _ = datastore
    for ms in (10.0, 12.0, 14.0):
        _insert(conn, metric=LATENCY_PRE_TURN_TOTAL, duration_ms=ms)

    tile = _tiles(conn)[LATENCY_PRE_TURN_TOTAL]
    assert tile["budget_ms"] == PRE_TURN_READ_SLO_P95_MS
    assert tile["breached"] is False

    _insert(conn, metric=LATENCY_PRE_TURN_TOTAL, duration_ms=900.0)
    _insert(conn, metric=LATENCY_PRE_TURN_TOTAL, duration_ms=900.0)
    assert _tiles(conn)[LATENCY_PRE_TURN_TOTAL]["breached"] is True


def test_the_admin_read_carries_the_latency_block(datastore) -> None:
    driver, conn, _ = datastore
    _insert(conn, metric=LATENCY_L4_LOAD, duration_ms=42.0)

    result = execute_tool(
        tool="toee_metrics",
        action="get_aggregate_metrics",
        params={},
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    )
    assert result.ok, result
    latency = result.data["latency"]
    assert latency["slo_p95_ms"] == PRE_TURN_READ_SLO_P95_MS
    tiles = {tile["metric"]: tile for tile in latency["layers"]}
    assert tiles[LATENCY_L4_LOAD]["p50_ms"] == pytest.approx(42.0)


class _SharedConn:
    """The fixture's connection, lent to the emit without letting it close it.

    ``emit_metric_samples`` uses ``with psycopg.connect(...) as conn``, which on
    psycopg3 commits AND closes on exit -- so the emit gets a proxy whose
    ``__exit__`` is a no-op and the throwaway schema survives to be read back.
    """

    def __init__(self, conn) -> None:
        self._conn = conn

    def __enter__(self) -> "_SharedConn":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def cursor(self):
        return self._conn.cursor()

    def commit(self) -> None:
        self._conn.commit()


class _SlowStore:
    def load_customer_memory(self, binding_key):
        time.sleep(0.04)
        return [{"slot": "contact_time", "value": "evenings"}]

    def load_confirmed_experience(self):
        return [{"id": "aexp_1", "content": "Check delivery status first.", "kind": "procedure"}]

    def load_confirmed_lexicon(self):
        return []

    def record_injection_ledger(self, **_kwargs):
        return None


def test_a_real_turn_round_trips_from_the_emit_into_the_tiles(
    datastore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The join the other two test files each fake one half of.

    ``test_latency.py`` fakes the WRITE (it intercepts the emit); the tests above
    fake the ROWS (they INSERT them by hand). Neither would notice if the emit
    wrote a shape the aggregation cannot read -- a column name typo, a metric name
    the tile catalog does not list, a duration on the wrong side of the NULL
    filter. This drives a real turn through the real writer into the real
    percentile query and reads the tile back.
    """
    _driver, conn, _ = datastore
    monkeypatch.setattr(
        "hermes_runtime.metrics.psycopg.connect", lambda *a, **k: _SharedConn(conn)
    )
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.setenv("AGENT_EXPERIENCE_EXTERNAL_INJECTION", "on")
    monkeypatch.setenv("LEXICON_EXTERNAL_INJECTION", "on")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    import hermes_runtime.openrouter as openrouter_mod

    monkeypatch.setattr(
        openrouter_mod, "run_agent_turn", lambda **_k: {"final_response": "R", "messages": []}
    )
    run_turn = make_openrouter_run_turn(
        config=OpenRouterConfig(
            base_url="https://openrouter.ai/api/v1",
            api_key="sk-or-test",
            model="m",
            fallback_model="f",
        ),
        openai_factory=_scripted_openai_factory([{"content": "ok"}]),
        store=_SlowStore(),
    )
    run_turn(
        SimpleNamespace(
            event_id="evt-roundtrip",
            conversation_id="conv-roundtrip",
            sms_session_id=None,
            from_phone="+14165550001",
            session_identity_snapshot=None,
        ),
        "Hi",
    )

    tiles = _tiles(conn)
    # One turn, so exactly one sample per read layer and one total.
    assert tiles[LATENCY_L4_LOAD]["samples"] == 1
    assert tiles[LATENCY_L6_LOAD]["samples"] == 1
    assert tiles[LATENCY_PRE_TURN_TOTAL]["samples"] == 1
    # ... and the number that survived the round trip is the one that was spent.
    assert tiles[LATENCY_L4_LOAD]["p95_ms"] >= 25.0
    assert tiles[LATENCY_L6_LOAD]["p95_ms"] < 25.0
    assert tiles[LATENCY_PRE_TURN_TOTAL]["p95_ms"] >= tiles[LATENCY_L4_LOAD]["p95_ms"]


def test_the_schema_refuses_a_row_that_carries_neither_signal(datastore) -> None:
    # 0023 drops `flag NOT NULL` so a latency sample can say "no boolean here".
    # The CHECK is what keeps that from becoming "a counter emit may silently
    # write nothing at all".
    import psycopg

    _driver, conn, _ = datastore
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert(conn, metric="memory_injection")
    conn.rollback()
