"""Shared async agent-turn job: reload, verify binding, run (ADR-0106/0107).

The protected internal route (Cloud Tasks delivery in production) and the local
in-process dispatcher both need the *same* guarded turn execution. Centralizing it
here keeps the two entry points from drifting: memory is the source of truth, so the
job reloads the context by ``event_id`` and verifies the supplied conversation
binding before any turn runs (ADR-0107). The route maps :class:`AgentJobOutcome` to
an HTTP status; the dispatcher logs it.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional, Protocol

from toee_hermes.gateway.agent_turn import (
    AgentJobPayload,
    AgentTurnContext,
    job_payload_matches,
)


class _ContextStore(Protocol):
    """The reload half of the GatewayStore seam the job depends on."""

    def load_context(self, event_id: str) -> Optional[AgentTurnContext]: ...

    def load_inbound_body(self, inbound_body_ref: str) -> Optional[str]: ...


class AgentJobOutcome(Enum):
    """Why a delivered agent-turn job did or did not run a turn."""

    CONTEXT_NOT_FOUND = "context_not_found"
    BINDING_MISMATCH = "binding_mismatch"
    COMPLETED = "completed"


def execute_agent_turn_job(
    *,
    store: _ContextStore,
    turn_runner: Optional[Any],
    payload: AgentJobPayload,
) -> AgentJobOutcome:
    """Reload + verify the binding, then run the turn (ADR-0107 source of truth).

    Returns ``CONTEXT_NOT_FOUND`` when no context is persisted for the eventId,
    ``BINDING_MISMATCH`` when the delivered conversation does not match the stored
    record (neither runs a turn), else ``COMPLETED`` after running ``turn_runner``
    (skipped when ``turn_runner`` is None, e.g. an unconfigured app).
    """
    context = store.load_context(payload.event_id)
    if context is None:
        return AgentJobOutcome.CONTEXT_NOT_FOUND
    if not job_payload_matches(context, payload):
        return AgentJobOutcome.BINDING_MISMATCH
    inbound_body = store.load_inbound_body(context.inbound_body_ref) or ""
    if turn_runner is not None:
        turn_runner(context, inbound_body)
    return AgentJobOutcome.COMPLETED
