"""AgentTurnContext persistence + Cloud Tasks payload (ADR-0107, ADR-0105).

The bridge between an accepted gateway decision and the async External Customer
Service Profile run. The gateway persists an :class:`AgentTurnContext` in Hermes
Native Memory before acking, then enqueues a minimal :class:`AgentJobPayload`
(eventId + conversationId). The async job reloads the context by ``event_id`` and
verifies the supplied ``conversation_id`` matches the stored record before the
agent turn — memory is the source of truth, not the task payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from toee_hermes.gateway.ingress import SessionIdentitySnapshot
from toee_hermes.gateway.pipeline import InboundDecision


@dataclass(frozen=True)
class AgentTurnContext:
    """Durable per-inbound-turn context reloaded by the async job (ADR-0107).

    ``channel`` (S17) threads the ingress channel to the async turn so the turn
    binds Customer Memory on the correct channel identity (email vs SMS). Defaulted
    to ``simpletexting_sms`` so pre-S17 construction sites remain byte-compatible.
    """

    event_id: str
    conversation_id: str
    sms_session_id: str
    customer_thread_id: str
    from_phone: str
    session_identity_snapshot: Optional[SessionIdentitySnapshot]
    inbound_body_ref: str
    channel: str = "simpletexting_sms"


@dataclass(frozen=True)
class AgentJobPayload:
    """Minimal Cloud Tasks payload (ADR-0105): identity keys only, no PII body."""

    event_id: str
    conversation_id: str


def build_agent_turn_context(
    decision: InboundDecision,
    *,
    sms_session_id: str,
    customer_thread_id: str,
    inbound_body_ref: str,
) -> AgentTurnContext:
    """Build the persisted context for an accepted (enqueue) inbound turn.

    Only enqueue decisions start an agent run; opt-out, rate-limited, duplicate,
    reject, and retry outcomes never produce an AgentTurnContext.
    """
    if not decision.enqueue or decision.event is None:
        raise ValueError(
            "AgentTurnContext is only built for an accepted (enqueue) decision "
            f"with a normalized event; got action={decision.action!r}."
        )
    event = decision.event
    return AgentTurnContext(
        event_id=event.event_id,
        conversation_id=event.conversation_id,
        sms_session_id=sms_session_id,
        customer_thread_id=customer_thread_id,
        from_phone=event.from_phone,
        session_identity_snapshot=decision.snapshot,
        inbound_body_ref=inbound_body_ref,
        channel=event.channel,
    )


def to_job_payload(context: AgentTurnContext) -> AgentJobPayload:
    return AgentJobPayload(
        event_id=context.event_id, conversation_id=context.conversation_id
    )


def job_payload_matches(
    context: AgentTurnContext, payload: AgentJobPayload
) -> bool:
    """Verify a delivered job payload binds to the stored turn (ADR-0107).

    Guards async reply authorization: the job runs only when both the idempotency
    key and the conversation binding match the persisted record.
    """
    return (
        context.event_id == payload.event_id
        and context.conversation_id == payload.conversation_id
    )
