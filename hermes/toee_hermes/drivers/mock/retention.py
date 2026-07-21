"""Retention windows + mock handlers for ``toee_retention`` (0.0.3 S28, FR-30).

Extends ADR-0004/0116's Customer Memory retention classes with a scheduled/
manually-triggerable sweep over ``customer_memory_slot``: age basis is
``last_interaction_at`` (the window refreshes on interaction, ADR-0116), never
``created_at``. The window sizes below are the ONE source of truth both the
mock and Postgres datastore handlers import, so the two twins can't drift on
what counts as "aged" (the same discipline ``resolve_customer_memory_binding``
enforces for binding derivation).

Windows:
  * ``verified``: 2 years (ADR-0116, non-negotiable).
  * ``provisional``: 90 days -- ADR-0116 only ever set the verified window;
    provisional preference copies are normally REMOVED on merge (ADR-0112), so
    it never addressed an ORPHANED provisional slot that never merged. See
    ``docs/adr/0116-conversation-and-customer-memory-retention.md``'s "0.0.3
    S28 addendum" for the recorded rationale (weaker identity confidence, no
    reason to hold past the point a merge realistically still happens).
    Deliberately shorter than the verified window, per FR-30's acceptance.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .driver import MockHandlerRegistry

if TYPE_CHECKING:
    from ...tool_gate import ToolExecutionContext

VERIFIED_RETENTION_DAYS = 730

# ponytail: 90 days -- conservative, calibratable window for orphaned unmerged
# provisional slots (see module docstring + ADR-0116 addendum for the
# rationale). Bump this constant, not the logic, if 90 proves too
# short/long in practice.
PROVISIONAL_RETENTION_DAYS = 90

RETENTION_WINDOW_DAYS: dict[str, int] = {
    "verified": VERIFIED_RETENTION_DAYS,
    "provisional": PROVISIONAL_RETENTION_DAYS,
}


def retention_threshold(binding_kind: str, now: datetime) -> datetime:
    """The cutoff timestamp for ``binding_kind``: older than this is aged out.

    Falls back to the longer (safer) verified window for any unrecognized
    ``binding_kind``, so an unclassified/future kind is never swept more
    aggressively than the conservative default -- no over-deletion (S28).
    """
    days = RETENTION_WINDOW_DAYS.get(binding_kind, VERIFIED_RETENTION_DAYS)
    return now - timedelta(days=days)


def is_aged(binding_kind: str, last_interaction_at: datetime, now: datetime) -> bool:
    """True when a ``customer_memory_slot`` row is past its class retention window."""
    return last_interaction_at < retention_threshold(binding_kind, now)


def create_retention_mock_handlers() -> MockHandlerRegistry:
    """Mock handlers for ``toee_retention`` -- admin-only, never LLM-callable.

    Mirrors ``toee_metrics``'s mock twin: there is no shared persisted store
    behind the mock fragments (each factory call closes over its own
    throwaway data, ADR-0137), so ``customer_memory_slot`` has nothing to
    sweep in mock mode. A zero-valued/never-run stub is structurally correct
    here (no data exists to age out), not a fabricated number; the real
    counts only ever come from the Postgres twin
    (``hermes_runtime.datastore.handlers.retention``).
    """

    def trigger_retention_sweep(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        return {
            "counts": {"verified": 0, "provisional": 0},
            "total_deleted": 0,
            "windows_days": dict(RETENTION_WINDOW_DAYS),
            "run_at": None,
        }

    def get_retention_status(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        return {
            "last_run_at": None,
            "counts": {"verified": 0, "provisional": 0},
            "total_deleted": 0,
            "windows_days": dict(RETENTION_WINDOW_DAYS),
        }

    return {
        "toee_retention": {
            "trigger_retention_sweep": trigger_retention_sweep,
            "get_retention_status": get_retention_status,
        }
    }
