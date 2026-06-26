"""AgentTurnContext + Cloud Tasks payload tests (ADR-0107, ADR-0105).

The gateway persists an AgentTurnContext for an accepted inbound turn and
enqueues a minimal task (eventId + conversationId). The async job reloads the
context by eventId and verifies the supplied conversationId matches the stored
record before running the External Customer Service Profile.
"""

from __future__ import annotations

import pytest

from toee_hermes.gateway.agent_turn import (
    AgentJobPayload,
    AgentTurnContext,
    build_agent_turn_context,
    job_payload_matches,
    to_job_payload,
)
from toee_hermes.gateway.ingress import SessionIdentitySnapshot
from toee_hermes.gateway.normalize import InboundChannelEvent
from toee_hermes.gateway.pipeline import InboundDecision

RESOLVED_AT = "2026-06-19T12:00:00.000Z"


def _event() -> InboundChannelEvent:
    return InboundChannelEvent(
        channel="textline_sms",
        provider="textline",
        event_id="evt_1",
        conversation_id="conv_9",
        from_phone="+14165550101",
        body="where is my order?",
        received_at=RESOLVED_AT,
        raw_event_type="message:received",
    )


def _accepted() -> InboundDecision:
    return InboundDecision(
        status=200,
        action="enqueue",
        stage="accept",
        event=_event(),
        snapshot=SessionIdentitySnapshot(
            outcome="verified_customer",
            resolved_at=RESOLVED_AT,
            shopify_customer_id="gid://shopify/Customer/1001",
        ),
    )


def test_builds_context_from_accepted_decision() -> None:
    context = build_agent_turn_context(
        _accepted(),
        sms_session_id="sess_1",
        customer_thread_id="thread_1",
        inbound_body_ref="msg_ref_1",
    )
    assert context == AgentTurnContext(
        event_id="evt_1",
        conversation_id="conv_9",
        sms_session_id="sess_1",
        customer_thread_id="thread_1",
        from_phone="+14165550101",
        session_identity_snapshot=SessionIdentitySnapshot(
            outcome="verified_customer",
            resolved_at=RESOLVED_AT,
            shopify_customer_id="gid://shopify/Customer/1001",
        ),
        inbound_body_ref="msg_ref_1",
    )


def test_job_payload_is_minimal() -> None:
    payload = to_job_payload(
        build_agent_turn_context(
            _accepted(),
            sms_session_id="sess_1",
            customer_thread_id="thread_1",
            inbound_body_ref="msg_ref_1",
        )
    )
    assert payload == AgentJobPayload(event_id="evt_1", conversation_id="conv_9")


def test_payload_matches_when_conversation_matches() -> None:
    context = build_agent_turn_context(
        _accepted(),
        sms_session_id="sess_1",
        customer_thread_id="thread_1",
        inbound_body_ref="msg_ref_1",
    )
    assert job_payload_matches(context, to_job_payload(context)) is True


def test_payload_mismatch_is_rejected() -> None:
    context = build_agent_turn_context(
        _accepted(),
        sms_session_id="sess_1",
        customer_thread_id="thread_1",
        inbound_body_ref="msg_ref_1",
    )
    spoofed = AgentJobPayload(event_id="evt_1", conversation_id="conv_OTHER")
    assert job_payload_matches(context, spoofed) is False


def test_build_requires_enqueue_decision() -> None:
    rejected = InboundDecision(status=401, action="reject", stage="verify")
    with pytest.raises(ValueError):
        build_agent_turn_context(
            rejected,
            sms_session_id="sess_1",
            customer_thread_id="thread_1",
            inbound_body_ref="msg_ref_1",
        )
