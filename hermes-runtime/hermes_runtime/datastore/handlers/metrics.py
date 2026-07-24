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

from ...honored_rate import honored_rate_metric

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
        cur.execute(
            """
            SELECT metric, COUNT(*) FILTER (WHERE flag) AS hits, COUNT(*) AS total
            FROM metric_event
            WHERE metric IN ('memory_injection', 'knowledge_search',
                             'self_service_usage', 'l6_confirmed_entries')
            GROUP BY metric
            """
        )
        counters = {metric: (hits, total) for metric, hits, total in cur.fetchall()}
        mem_hits, mem_total = counters.get("memory_injection", (0, 0))
        know_hits, know_total = counters.get("knowledge_search", (0, 0))
        self_service_count = counters.get("self_service_usage", (0, 0))[1]
        l6_confirmed_count = counters.get("l6_confirmed_entries", (0, 0))[1]

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
        # proxied -- plain totals like merge_count/correction_count above.
        "self_service_usage": self_service_count,
        "l6_confirmed_entries": l6_confirmed_count,
    }


def metrics_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the aggregate-metrics admin-panel tool."""
    return {"toee_metrics": {"get_aggregate_metrics": _get_aggregate_metrics}}
