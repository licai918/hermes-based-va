"""Datastore handler for ``toee_metrics`` -- the aggregate-metrics admin panel
(0.0.3 S26, FR-28).

Some FR-28 metrics are cheap SQL aggregations over EXISTING tables
(``customer_memory_slot``, ``customer_memory_merge_audit``,
``workbench_audit_log``, ``agent_experience``); the rest read the
``metric_event`` counter table (migration 0009). Memory-injection and
knowledge-found rates are hits/total pairs (``tool_backend.record_memory_
injection_metric``, ``knowledge/driver.py._emit_found``). Self-service usage and
L6-confirmed entries (0.0.4 S21, FR-30) are plain once-per-action totals emitted
in-transaction at their governed sites (``handlers/memory.py`` customer clear,
``handlers/agent_experience.py`` confirm) -- no longer the pre-S21 audit-log/
status-count proxies. Honored rate is judge-sampled (S27) and advisory -- NEVER
gating -- and genuinely cannot be computed inline here (it requires an LLM judge
call over sampled live turns), so a scheduled ``honored_rate`` background job
(0.0.4 S22, FR-31) runs the judge and persists an aggregate this handler reads
the LATEST of (``hermes_runtime.honored_rate.honored_rate_metric``). With no
aggregate yet it returns the honest ``live=False`` "not yet computed" state --
never a silent zero, never a fabricated rate.

Read-only, admin-only: never registered as an LLM-callable tool (see
``_AGENT_EXCLUDED_ACTIONS``) -- reached only from the admin BFF's
deterministic ``tools:dispatch`` call, same precedent as ``get_memory_audit``/
``list_agent_experience``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable, Optional

from toee_hermes.drivers.mock.memory import (
    MEMORY_ACTION_ERASED,
    MEMORY_ACTION_PREFERENCE_UPDATED,
)
from toee_hermes.lifecycle_metrics import lifecycle_payload

from ...honored_rate import honored_rate_metric
from ...knobs import knob_panel
from ...latency import _METRIC_LAYER, SLO_TOTAL_METRICS, latency_metrics, skip_metric
from ...loop_closure import loop_closure_metrics
from ._common import (
    METRIC_L6_CONFIRMED,
    METRIC_MEMORY_POLLUTION_REJECTED,
    METRIC_SELF_SERVICE_USAGE,
)
from .memory import deletion_success_metric

# 0.0.5 S22: the metric name a dropped layer records -> the layer it dropped,
# DERIVED from the two tables `latency` already owns rather than restated. S19
# emits the skip rows and left the tile to this slice; a second copy of the
# metric->layer mapping is exactly how the L6 hole D4.1 corrected got in.
_DROP_METRIC_LAYER = {
    skip_metric(metric): _METRIC_LAYER[metric].upper() for metric in SLO_TOTAL_METRICS
}

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext

def _rate(hits: int, total: int) -> Optional[float]:
    """``hits / total``, rounded, or ``None`` when there is no denominator."""
    return round(hits / total, 4) if total else None


def _distribution_dict(rows: Iterable[tuple[int, int]]) -> dict[str, int]:
    """``[(populated_count, customers), ...]`` -> the fixed 1-4 histogram dict.

    ``customer_memory_slot``'s ``UNIQUE(binding_key, slot_name)`` caps a
    binding at the 4 v1 slots, so a populated count outside 1-4 should never
    occur; it is defensively ignored rather than raised (a read must never
    fail the admin panel over a data shape surprise)."""
    dist = {str(n): 0 for n in range(1, 5)}
    for populated, count in rows:
        key = str(populated)
        if key in dist:
            dist[key] = count
    return dist


def _get_aggregate_metrics(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    with conn.cursor() as cur:
        # --- GAP counters: metric_event (migration 0009) ---------------------
        # memory_injection/knowledge_search use the hits/total pair; the two
        # S21/FR-30 governed-action counters (self_service_usage, l6_confirmed_
        # entries) are plain totals emitted once per real action -- same table,
        # one query.
        # The two S21 counters share their metric name with the emit side via the
        # _common constants, so the emit and aggregation sides can't drift (the
        # _common docstring's promise). memory_injection/knowledge_search have no
        # shared constant (no separate emit-site literal to drift from).
        # S22/FR-34a adds the pollution counter and S19's per-layer drop
        # counters to the SAME query -- they are `metric_event` rows like the
        # rest, so a second round trip would buy nothing. The drop names are
        # derived (`skip_metric`), never spelled out here.
        cur.execute(
            """
            SELECT metric, COUNT(*) FILTER (WHERE flag) AS hits, COUNT(*) AS total
            FROM metric_event
            WHERE metric IN ('memory_injection', 'knowledge_search')
               OR metric = ANY(%s)
            GROUP BY metric
            """,
            (
                [
                    METRIC_SELF_SERVICE_USAGE,
                    METRIC_L6_CONFIRMED,
                    METRIC_MEMORY_POLLUTION_REJECTED,
                    *_DROP_METRIC_LAYER,
                ],
            ),
        )
        counters = {metric: (hits, total) for metric, hits, total in cur.fetchall()}
        mem_hits, mem_total = counters.get("memory_injection", (0, 0))
        know_hits, know_total = counters.get("knowledge_search", (0, 0))
        self_service_count = counters.get(METRIC_SELF_SERVICE_USAGE, (0, 0))[1]
        l6_confirmed_count = counters.get(METRIC_L6_CONFIRMED, (0, 0))[1]
        pollution_count = counters.get(METRIC_MEMORY_POLLUTION_REJECTED, (0, 0))[1]
        layer_drops = {
            layer: counters.get(metric, (0, 0))[1]
            for metric, layer in _DROP_METRIC_LAYER.items()
        }

        # --- slots-populated distribution: customer_memory_slot --------------
        cur.execute(
            """
            SELECT populated, COUNT(*) FROM (
                SELECT binding_key, COUNT(*) AS populated
                FROM customer_memory_slot
                GROUP BY binding_key
            ) per_binding
            GROUP BY populated
            """
        )
        distribution = _distribution_dict(cur.fetchall())

        # --- merge count: customer_memory_merge_audit -------------------------
        cur.execute("SELECT COUNT(*) FROM customer_memory_merge_audit")
        merge_count = cur.fetchone()[0]

        # --- correction count / proposal accept: employee_confirmed writes ---
        # NOTE (documented, S26 brief): accept has no distinct audit action, so
        # this may also count an organic employee correction, not only an
        # accepted S14 proposal -- counting what's honestly countable.
        cur.execute(
            "SELECT COUNT(*) FROM customer_memory_slot WHERE source = 'employee_confirmed'"
        )
        correction_count = cur.fetchone()[0]

        # --- proposal dismiss: workbench_audit_log ----------------------------
        cur.execute(
            "SELECT COUNT(*) FROM workbench_audit_log WHERE action = 'proposal_dismissed'"
        )
        dismissed_count = cur.fetchone()[0]

        # --- honored rate: latest honored_rate_aggregate (S22, FR-31) ---------
        # Read the LATEST aggregate the scheduled honored_rate job persisted; an
        # empty table returns the honest "not yet computed" state, never a zero.
        honored_rate = honored_rate_metric(cur)

        # --- per-layer read latency: metric_event.duration_ms (S18, FR-26) ----
        # Same table, different shape: `duration_ms IS NOT NULL` separates the
        # latency samples from the boolean counters above, which is why
        # knowledge_search can be both without either query seeing the other.
        latency = latency_metrics(cur)

        # --- deletion success: the FR-14 tripwire (0.0.5 S11) -----------------
        # Deterministic SQL over workbench_audit_log + customer_memory_slot,
        # owned by handlers/memory.py so the query and the `memory_erased` row
        # it anchors on live beside each other. S22 places the tile.
        deletion_success = deletion_success_metric(cur)

        # --- lifecycle counts: workbench_audit_log (0.0.5 S22, FR-34a) --------
        # ONE grouped query over the two governed actions FR-34a counts, keyed
        # by the SAME action constants the emit sites use, so the count and the
        # row it counts cannot drift into two spellings. Scoped by `action`
        # alone on purpose: an erase writes one summary row per binding, and a
        # differing-value overwrite writes exactly one row, so the row IS the
        # event -- no DISTINCT, and no join that could multiply either.
        cur.execute(
            "SELECT action, COUNT(*) FROM workbench_audit_log "
            "WHERE action = ANY(%s) GROUP BY action",
            ([MEMORY_ACTION_PREFERENCE_UPDATED, MEMORY_ACTION_ERASED],),
        )
        lifecycle_audit = dict(cur.fetchall())

    # --- loop closure: conversion / re-fail / entry trend (0.0.5 S28, FR-34b) --
    # Takes the CONNECTION, not the cursor above: its three queries each open
    # their own default-row-factory cursor, which is also what keeps them from
    # inheriting a dict_row cursor a neighbouring read might have wanted (the
    # trap `entry_effectiveness_for` documents).
    loop_closure = loop_closure_metrics(conn)

    accepted_total = correction_count + dismissed_count

    return {
        "memory_injection": {
            "injected": mem_hits,
            "total": mem_total,
            "rate": _rate(mem_hits, mem_total),
        },
        "knowledge_search": {
            "found": know_hits,
            "total": know_total,
            "rate": _rate(know_hits, know_total),
        },
        "slots_populated_distribution": distribution,
        "honored_rate": honored_rate,
        "merge_count": merge_count,
        "correction_count": correction_count,
        "proposal_outcomes": {
            "accepted": correction_count,
            "dismissed": dismissed_count,
            "rate": _rate(correction_count, accepted_total),
        },
        # S21/FR-30: real once-per-action counters (metric_event), no longer
        # proxied -- plain totals like merge_count/correction_count above. Keyed by
        # the shared _common constants (identical values) so the output contract can't
        # drift from the emit side.
        METRIC_SELF_SERVICE_USAGE: self_service_count,
        METRIC_L6_CONFIRMED: l6_confirmed_count,
        # S18/FR-26: p50/p95 per memory layer + the total-vs-SLO tile. Shape owned
        # by hermes_runtime.latency so the mock twin renders the same tiles.
        "latency": latency,
        # S11/FR-14: cleared-and-stayed-cleared. Shape owned by the shared L4
        # module (toee_hermes.drivers.mock.memory.deletion_success_payload), which
        # the mock twin calls too -- one builder, not two spellings.
        "deletion_success": deletion_success,
        # S22/FR-34a: conflict, pollution, privacy-deflection proxy and the
        # per-layer prompt drops. Same shared-builder posture as
        # `deletion_success` above -- the mock twin calls `lifecycle_payload`
        # with no counts, so neither twin can invent a tile the other lacks.
        **lifecycle_payload(
            conflict_overwrites=lifecycle_audit.get(MEMORY_ACTION_PREFERENCE_UPDATED, 0),
            pollution_rejected=pollution_count,
            self_service_clears=self_service_count,
            binding_erasures=lifecycle_audit.get(MEMORY_ACTION_ERASED, 0),
            layer_drops=layer_drops,
        ),
        # S28/FR-34b: did the loop CLOSE? Conversion, post-fix re-fail and the
        # per-entry honored trend after an edit. Same shared-builder posture as
        # the lifecycle block above -- the mock twin calls `loop_closure_payload`
        # with no counts, so neither twin can invent a rate the other lacks.
        **loop_closure,
        # S22/FR-34a: the READ-ONLY knob panel (D14). Postgres-side only -- see
        # `hermes_runtime.knobs` for why the mock twin reports null here rather
        # than a copy of these values.
        "knobs": knob_panel(),
    }


def metrics_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the aggregate-metrics admin-panel tool."""
    return {"toee_metrics": {"get_aggregate_metrics": _get_aggregate_metrics}}
