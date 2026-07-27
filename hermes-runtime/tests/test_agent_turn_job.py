"""Shared async agent-turn job logic (ADR-0106/0107).

The protected internal route and the local job dispatcher must run the *same*
guarded turn: reload the context by eventId, verify the conversation binding, then
run the turn against the loaded body (memory is the source of truth, not the task
payload). :func:`execute_agent_turn_job` is that one shared decision; the route maps
its outcome to an HTTP status and the dispatcher logs it.
"""

from __future__ import annotations

from typing import Optional

from toee_hermes.gateway.agent_turn import AgentJobPayload, AgentTurnContext

from hermes_runtime.agent_turn_job import AgentJobOutcome, execute_agent_turn_job


def _context(
    *, event_id: str = "evt-1", conversation_id: str = "conv-1"
) -> AgentTurnContext:
    return AgentTurnContext(
        event_id=event_id,
        conversation_id=conversation_id,
        sms_session_id="sess-1",
        customer_thread_id="thread-1",
        from_phone="+15551230000",
        session_identity_snapshot=None,
        inbound_body_ref="body-ref-1",
    )


class _FakeStore:
    """The 3-method GatewayStore seam, just enough to drive the job."""

    def __init__(
        self, *, context: Optional[AgentTurnContext], body: str = ""
    ) -> None:
        self._context = context
        self._body = body

    def load_context(self, event_id: str) -> Optional[AgentTurnContext]:
        return self._context

    def load_inbound_body(self, inbound_body_ref: str) -> Optional[str]:
        return self._body


def test_runs_the_turn_with_the_loaded_context_and_body_for_a_matching_job() -> None:
    runs: list[tuple[str, str, str]] = []
    store = _FakeStore(context=_context(), body="Where is my order?")
    payload = AgentJobPayload(event_id="evt-1", conversation_id="conv-1")

    outcome = execute_agent_turn_job(
        store=store,
        turn_runner=lambda ctx, body, job_id: runs.append(
            (ctx.event_id, ctx.conversation_id, body)
        ),
        payload=payload,
    )

    assert outcome is AgentJobOutcome.COMPLETED
    assert runs == [("evt-1", "conv-1", "Where is my order?")]


def test_returns_context_not_found_and_runs_nothing_when_context_is_absent() -> None:
    runs: list[str] = []
    store = _FakeStore(context=None)
    payload = AgentJobPayload(event_id="missing", conversation_id="conv-1")

    outcome = execute_agent_turn_job(
        store=store,
        turn_runner=lambda ctx, body, job_id: runs.append(ctx.event_id),
        payload=payload,
    )

    assert outcome is AgentJobOutcome.CONTEXT_NOT_FOUND
    assert runs == []


def test_returns_binding_mismatch_and_runs_nothing_when_conversation_differs() -> None:
    runs: list[str] = []
    store = _FakeStore(context=_context(conversation_id="conv-1"))
    payload = AgentJobPayload(event_id="evt-1", conversation_id="conv-OTHER")

    outcome = execute_agent_turn_job(
        store=store,
        turn_runner=lambda ctx, body, job_id: runs.append(ctx.event_id),
        payload=payload,
    )

    assert outcome is AgentJobOutcome.BINDING_MISMATCH
    assert runs == []
