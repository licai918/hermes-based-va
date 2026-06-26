"""Local in-process job dispatcher (ADR-0105 local substrate, ADR-0103 fast-ack).

In production Cloud Tasks POSTs each accepted turn to the protected internal route;
locally there is no task service, so :class:`LocalDispatchingJobQueue` runs the same
shared :func:`execute_agent_turn_job` out-of-band. Two properties matter: the turn
actually runs (so a locally-booted app replies), and ``enqueue`` returns immediately
without blocking the webhook on the turn (fast-ack). The dispatch mechanism is
injected so the wiring is asserted synchronously; one test exercises the real
background-thread default to pin the fast-ack property.
"""

from __future__ import annotations

import threading
from typing import Optional

from toee_hermes.gateway.agent_turn import AgentJobPayload, AgentTurnContext

from hermes_runtime.job_dispatch import LocalDispatchingJobQueue


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
    def __init__(
        self, *, context: Optional[AgentTurnContext], body: str = ""
    ) -> None:
        self._context = context
        self._body = body

    def load_context(self, event_id: str) -> Optional[AgentTurnContext]:
        return self._context

    def load_inbound_body(self, inbound_body_ref: str) -> Optional[str]:
        return self._body


def test_enqueue_runs_the_bound_turn_through_the_shared_job() -> None:
    runs: list[tuple[str, str]] = []
    store = _FakeStore(context=_context(), body="Where is my order?")
    queue = LocalDispatchingJobQueue(
        store=store,
        turn_runner=lambda ctx, body: runs.append((ctx.conversation_id, body)),
        dispatch=lambda work: work(),  # run inline for a deterministic assertion
    )

    queue.enqueue(AgentJobPayload(event_id="evt-1", conversation_id="conv-1"))

    assert runs == [("conv-1", "Where is my order?")]


def test_enqueue_runs_nothing_when_the_binding_does_not_match() -> None:
    runs: list[str] = []
    store = _FakeStore(context=_context(conversation_id="conv-1"))
    queue = LocalDispatchingJobQueue(
        store=store,
        turn_runner=lambda ctx, body: runs.append(ctx.event_id),
        dispatch=lambda work: work(),
    )

    queue.enqueue(AgentJobPayload(event_id="evt-1", conversation_id="conv-OTHER"))

    assert runs == []


def test_a_failing_turn_is_reported_to_on_error_not_swallowed_silently() -> None:
    # ADR-0104: a turn that raises out-of-band (e.g. both models down, or the
    # Textline send fails) must surface, not vanish in a dead background thread. The
    # dispatcher routes it to on_error (default: log) instead of propagating.
    errors: list[tuple[str, str]] = []
    store = _FakeStore(context=_context(), body="hi")

    def boom(ctx: object, body: str) -> None:
        raise RuntimeError("textline unreachable")

    queue = LocalDispatchingJobQueue(
        store=store,
        turn_runner=boom,
        dispatch=lambda work: work(),
        on_error=lambda payload, exc: errors.append(
            (payload.event_id, type(exc).__name__)
        ),
    )

    # enqueue does not raise even though the turn failed:
    queue.enqueue(AgentJobPayload(event_id="evt-1", conversation_id="conv-1"))

    assert errors == [("evt-1", "RuntimeError")]


def test_enqueue_fast_acks_by_running_the_turn_out_of_band() -> None:
    # The default dispatch runs the turn on a background thread so enqueue (called
    # inside the webhook handler) returns before the turn completes (ADR-0103).
    release = threading.Event()
    completed = threading.Event()

    def blocking_turn(ctx: object, body: str) -> None:
        release.wait(timeout=2)
        completed.set()

    store = _FakeStore(context=_context(), body="hi")
    queue = LocalDispatchingJobQueue(store=store, turn_runner=blocking_turn)

    queue.enqueue(AgentJobPayload(event_id="evt-1", conversation_id="conv-1"))

    # enqueue returned while the turn is still blocked: it did not wait on the turn.
    assert not completed.is_set()
    release.set()
    assert completed.wait(timeout=2)
