"""Mock handler for ``toee_metrics`` (0.0.3 S26, FR-28).

The mock driver has no aggregate view to compute over -- there is no shared
persisted store behind the in-memory mock fragments (each factory call closes
over its own throwaway data, ADR-0137) -- so this returns a STATIC zero-valued
stub in the exact same shape :func:`hermes_runtime.datastore.handlers.metrics.
_get_aggregate_metrics` returns. A zero on a mock/dev-without-datastore
deployment is structurally correct (no data exists to aggregate), not a
fabricated number; the real counts only ever come from the Postgres twin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .driver import MockHandlerRegistry

if TYPE_CHECKING:
    from ...tool_gate import ToolExecutionContext

# The honored rate comes from a scheduled judge job that persists an aggregate
# (0.0.4 S22, FR-31) -- there is no store behind the mock, so it always reports the
# honest "not yet computed" state, the same shape the Postgres twin returns before
# the first run (hermes_runtime.honored_rate.honored_rate_metric). A zero would be a
# fabricated rate; None over live=False is the truth on a storeless deployment.
_HONORED_RATE_LABEL = (
    "Honored rate is advisory and judge-sampled (S22/S27, C7 core question) -- "
    "never gating. Not yet computed on this deployment (no persisted aggregate)."
)

# Not-computed shape, kept in one place so it stays byte-identical to the Postgres
# twin's never-run branch (both feed the same BFF mapper, which requires the keys).
_HONORED_RATE_NOT_COMPUTED = {
    "live": False,
    "rate": None,
    "sample_size": None,
    "candidate_total": None,
    "undetermined_count": None,
    "window_seconds": None,
    "as_of": None,
    "label": _HONORED_RATE_LABEL,
}


def create_metrics_mock_handlers() -> MockHandlerRegistry:
    def get_aggregate_metrics(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        return {
            "memory_injection": {"injected": 0, "total": 0, "rate": None},
            "knowledge_search": {"found": 0, "total": 0, "rate": None},
            "slots_populated_distribution": {"1": 0, "2": 0, "3": 0, "4": 0},
            "honored_rate": dict(_HONORED_RATE_NOT_COMPUTED),
            "merge_count": 0,
            "correction_count": 0,
            "proposal_outcomes": {"accepted": 0, "dismissed": 0, "rate": None},
            # S21/FR-30: real once-per-action counters (metric_event), no longer
            # proxied -- plain totals, zero on a storeless mock deployment.
            "self_service_usage": 0,
            "l6_confirmed_entries": 0,
        }

    return {"toee_metrics": {"get_aggregate_metrics": get_aggregate_metrics}}
