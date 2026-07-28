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

from ...lifecycle_metrics import lifecycle_payload
from .driver import MockHandlerRegistry
from .memory import deletion_success_payload

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
    # S21 (0.0.5 FR-28): per-leg advisory counts from the scheduled judge run.
    # Empty on a storeless mock for the same reason the rate is None -- there is
    # no aggregate to break down, and an empty map is the honest form of that.
    "leg_results": {},
    "label": _HONORED_RATE_LABEL,
}


# S18 (0.0.5 FR-26): per-layer read-latency tiles. Same reasoning as the honored
# rate -- there is no store behind the mock, so every tile is honestly "not yet
# measured" rather than a fabricated 0ms, which would render as the best possible
# latency on a deployment that has measured nothing.
#
# This restates ``hermes_runtime.latency.empty_latency_metrics()`` rather than
# importing it: ``hermes_runtime`` depends on ``toee_hermes``, so importing back
# would invert the package dependency. The restatement is not left to trust --
# ``tests/test_latency.py::test_the_mock_twin_reports_the_same_zero_sample_payload``
# asserts FULL equality with the Postgres twin's zero-sample payload, so any
# drift in either direction is red rather than a silently different panel.
_LATENCY_SLO_P95_MS = 150.0
_LATENCY_L5_BUDGET_MS = 800.0
_LATENCY_NOT_MEASURED_LABEL = "Not yet measured (no latency samples on this deployment)"
# (metric, layer, label, budget_ms, in_slo_total)
_LATENCY_TILES = (
    ("latency_l4_load", "L4", "L4 customer memory read", None, True),
    ("latency_l6_load", "L6", "L6 confirmed learnings read", None, True),
    ("latency_l7_load", "L7", "L7 lexicon glossary read", None, True),
    ("latency_l4_merge", "L4", "L4 provisional merge (write)", None, False),
    ("knowledge_search", "L5", "L5 knowledge retrieval", _LATENCY_L5_BUDGET_MS, False),
)
_LATENCY_TOTAL_TILE = (
    "latency_pre_turn_total",
    "L4+L6+L7",
    "Pre-turn reads, total",
    _LATENCY_SLO_P95_MS,
    False,
)


def _latency_tile(metric, layer, label, budget_ms, in_slo_total) -> dict[str, Any]:
    return {
        "metric": metric,
        "layer": layer,
        "label": label,
        "p50_ms": None,
        "p95_ms": None,
        "samples": 0,
        "budget_ms": budget_ms,
        "in_slo_total": in_slo_total,
        # None, never False: "no verdict", not "within budget".
        "breached": None,
    }


def _latency_not_measured() -> dict[str, Any]:
    """Fresh per call -- the nested tiles are mutable, so a shared dict would hand
    every caller the same one (the ``leg_results`` lesson above)."""
    return {
        "slo_p95_ms": _LATENCY_SLO_P95_MS,
        "not_measured_label": _LATENCY_NOT_MEASURED_LABEL,
        "total": _latency_tile(*_LATENCY_TOTAL_TILE),
        "layers": [_latency_tile(*spec) for spec in _LATENCY_TILES],
    }


def create_metrics_mock_handlers() -> MockHandlerRegistry:
    def get_aggregate_metrics(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        return {
            "memory_injection": {"injected": 0, "total": 0, "rate": None},
            "knowledge_search": {"found": 0, "total": 0, "rate": None},
            "slots_populated_distribution": {"1": 0, "2": 0, "3": 0, "4": 0},
            # Fresh leg_results per call: the only mutable value in the shape,
            # and a shallow dict() copy would hand every caller the same one.
            "honored_rate": {**_HONORED_RATE_NOT_COMPUTED, "leg_results": {}},
            "merge_count": 0,
            "correction_count": 0,
            "proposal_outcomes": {"accepted": 0, "dismissed": 0, "rate": None},
            # S21/FR-30: real once-per-action counters (metric_event), no longer
            # proxied -- plain totals, zero on a storeless mock deployment.
            "self_service_usage": 0,
            "l6_confirmed_entries": 0,
            # S18/FR-26: honestly unmeasured, never a fabricated 0ms.
            "latency": _latency_not_measured(),
            # S11/FR-14: no erases on a storeless deployment, so zero erases and
            # a `None` rate -- NOT a 100% success rate, which is what a naive
            # zero-filled shape would render for a system that has erased
            # nothing. Unlike the two blocks above this calls the SHARED builder
            # rather than restating it: `deletion_success_payload` lives in this
            # package (the L4 module), so hermes_runtime imports it too and the
            # dependency direction never inverts.
            "deletion_success": deletion_success_payload(),
            # S22/FR-34a: same SHARED builder the Postgres twin calls, with no
            # counts -- a storeless deployment has recorded no overwrites, no
            # rejections and no erases, and zero is the true answer for each.
            # Every label and every "what is NOT in this number" caveat comes
            # from that one builder, so the two twins cannot drift.
            **lifecycle_payload(),
            # S22/FR-34a: the knob panel is `hermes_runtime`'s to build -- the
            # constants live there and this package must not import back (the
            # same reason the mock retention twin reports a null ledger-prune
            # window). `None` is the honest "this backend does not report
            # them"; a copy of the numbers would be wrong the day one is tuned.
            "knobs": None,
        }

    return {"toee_metrics": {"get_aggregate_metrics": get_aggregate_metrics}}
