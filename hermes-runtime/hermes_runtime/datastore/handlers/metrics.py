"""Datastore handler for ``toee_metrics`` -- the aggregate-metrics admin panel
(0.0.3 S26, FR-28).

Six of the eight FR-28 metrics are cheap SQL aggregations over EXISTING
tables (``customer_memory_slot``, ``customer_memory_merge_audit``,
``workbench_audit_log``, ``agent_experience``); memory-injection rate and
knowledge-found rate read the new ``metric_event`` counter table (migration
0009) two GAP producers now emit into (``tool_backend.record_memory_injection_
metric``, ``knowledge/driver.py._emit_found``). Honored rate is judge-sampled
(S27) and advisory -- NEVER gating -- and genuinely cannot be computed inline
here (it requires an LLM judge call over sampled live turns), so it ships as
an honestly-labeled non-live placeholder rather than a silent zero.

Read-only, admin-only: never registered as an LLM-callable tool (see
``_AGENT_EXCLUDED_ACTIONS``) -- reached only from the admin BFF's
deterministic ``tools:dispatch`` call, same precedent as ``get_memory_audit``/
``list_agent_experience``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext

# Advisory, judge-sampled (S27, C7 core question, audit finding 6) -- this
# panel never computes it inline (that would mean an LLM judge call on every
# admin page load) and never gates on it. Honestly labeled non-live rather
# than a silent zero (S26 brief discipline).
_HONORED_RATE_LABEL = (
    "Honored rate is advisory and judge-sampled (S27, C7 core question) -- "
    "never gating. Run `python -m eval_runner.judge_measure` (or a "
    "live-traffic sampler) against recorded turns to populate it."
)

_SELF_SERVICE_LABEL = (
    "proxy: counts customer-initiated preference clears "
    "(workbench_audit_log preference_cleared, initiator=customer); "
    "get_my_memory_summary reads are not separately counted (uninstrumented)."
)

_L6_LABEL = (
    "proxy: count of CONFIRMED L6 entries available for injection, not "
    "actual per-turn injection events (uninstrumented)."
)


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
        cur.execute(
            """
            SELECT metric, COUNT(*) FILTER (WHERE flag) AS hits, COUNT(*) AS total
            FROM metric_event
            WHERE metric IN ('memory_injection', 'knowledge_search')
            GROUP BY metric
            """
        )
        counters = {metric: (hits, total) for metric, hits, total in cur.fetchall()}
        mem_hits, mem_total = counters.get("memory_injection", (0, 0))
        know_hits, know_total = counters.get("knowledge_search", (0, 0))

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

        # --- self-service usage (proxy: customer-initiated clears) -----------
        cur.execute(
            """
            SELECT COUNT(*) FROM workbench_audit_log
            WHERE action = 'preference_cleared' AND details ->> 'initiator' = 'customer'
            """
        )
        self_service_count = cur.fetchone()[0]

        # --- L6 confirmed entries (proxy for per-turn injection events) ------
        cur.execute("SELECT COUNT(*) FROM agent_experience WHERE status = 'confirmed'")
        l6_confirmed_count = cur.fetchone()[0]

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
        "honored_rate": {"live": False, "rate": None, "label": _HONORED_RATE_LABEL},
        "merge_count": merge_count,
        "correction_count": correction_count,
        "proposal_outcomes": {
            "accepted": correction_count,
            "dismissed": dismissed_count,
            "rate": _rate(correction_count, accepted_total),
        },
        "self_service_usage": {
            "count": self_service_count,
            "proxy": True,
            "label": _SELF_SERVICE_LABEL,
        },
        "l6_confirmed_entries": {
            "count": l6_confirmed_count,
            "proxy": True,
            "label": _L6_LABEL,
        },
    }


def metrics_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the aggregate-metrics admin-panel tool."""
    return {"toee_metrics": {"get_aggregate_metrics": _get_aggregate_metrics}}
