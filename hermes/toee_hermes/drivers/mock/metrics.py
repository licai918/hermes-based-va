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

# Same advisory label the Postgres twin uses -- honored rate is judge-sampled
# (S27) and never computed inline here or there.
_HONORED_RATE_LABEL = (
    "Honored rate is advisory and judge-sampled (S27, C7 core question) -- "
    "never gating. Run the judge harness against recorded turns to populate it."
)


def create_metrics_mock_handlers() -> MockHandlerRegistry:
    def get_aggregate_metrics(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        return {
            "memory_injection": {"injected": 0, "total": 0, "rate": None},
            "knowledge_search": {"found": 0, "total": 0, "rate": None},
            "slots_populated_distribution": {"1": 0, "2": 0, "3": 0, "4": 0},
            "honored_rate": {"live": False, "rate": None, "label": _HONORED_RATE_LABEL},
            "merge_count": 0,
            "correction_count": 0,
            "proposal_outcomes": {"accepted": 0, "dismissed": 0, "rate": None},
            "self_service_usage": {
                "count": 0,
                "proxy": True,
                "label": (
                    "proxy: counts customer-initiated preference clears "
                    "(workbench_audit_log preference_cleared, initiator=customer); "
                    "get_my_memory_summary reads are not separately counted."
                ),
            },
            "l6_confirmed_entries": {
                "count": 0,
                "proxy": True,
                "label": (
                    "proxy: count of CONFIRMED L6 entries available for "
                    "injection, not actual per-turn injection events."
                ),
            },
        }

    return {"toee_metrics": {"get_aggregate_metrics": get_aggregate_metrics}}
