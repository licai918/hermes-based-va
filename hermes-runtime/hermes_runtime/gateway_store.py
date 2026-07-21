"""Gateway persistence + async enqueue seam (ADR-0105/0107/0115, ADR-0140).

The route layer hands each accepted inbound turn to the store before acking; the
store persists it **and enqueues its minimal turn job as one unit** (0.0.4 S02
fix wave 1 -- see :meth:`GatewayStore.persist_accepted_inbound`). The turn worker
then reloads the context by ``event_id`` (memory is the source of truth, not the
task payload, ADR-0107). These Protocols are the seam the real Toee Business
Datastore (Postgres, ADR-0140) implements; the in-memory versions are the
deterministic local-dev/test substrate so the gateway is runnable and testable
without a database.

The in-memory store mirrors the ADR-0115 entity hierarchy:

    CustomerThread (one per channel identity / phone)
      -> SmsSession (one per 24h window; dev maps one Textline conversation = one)
        -> MessageTurn (one per inbound/outbound/Hermes message event)
    AgentTurnContext (one per accepted inbound eventId; refs thread/session/turn)
"""

from __future__ import annotations

from typing import Optional, Protocol

from toee_hermes.gateway.agent_turn import (
    AgentJobPayload,
    AgentTurnContext,
    build_agent_turn_context,
    to_job_payload,
)
from toee_hermes.gateway.normalize import InboundChannelEvent, is_email_channel
from toee_hermes.gateway.pipeline import InboundDecision


class GatewayStore(Protocol):
    """Durable store for accepted inbound turns (ADR-0107 source of truth)."""

    def persist_accepted_inbound(
        self, decision: InboundDecision
    ) -> tuple[AgentTurnContext, bool]:
        """Persist an accepted inbound turn and enqueue its turn job atomically.

        The enqueue belongs to the implementation, not to the caller: the two
        writes must share a commit boundary or a crash between them loses an
        already-acked customer message (US3). ``bool`` is ``created`` -- False
        when this ``event_id`` was already persisted, in which case nothing new
        was enqueued either.
        """
        ...

    def load_context(self, event_id: str) -> Optional[AgentTurnContext]: ...

    def load_inbound_body(self, inbound_body_ref: str) -> Optional[str]: ...

    def persist_agent_outbound(self, context: AgentTurnContext, body: str) -> None: ...


class JobQueue(Protocol):
    """Async agent-turn dispatch seam for the **in-memory** store.

    Production does not go through this Protocol any more: the durable Postgres
    path (ADR-0153) enqueues inside ``PostgresGatewayStore``'s own transaction
    via :func:`hermes_runtime.job_queue.insert_job`, because a seam here is by
    construction a second commit boundary. What remains is the DB-free substrate
    -- :class:`InMemoryJobQueue` and the test doubles that run the job body
    inline.
    """

    def enqueue(self, payload: AgentJobPayload) -> None: ...


class InMemoryGatewayStore:
    """Deterministic in-memory implementation of the ADR-0115 entity hierarchy.

    ``queue`` is the DB-free stand-in for the Postgres store's in-transaction
    outbox: one process, one dict, so "atomic" is free here. Inject one to
    observe or to run the turn inline; the default records payloads for
    assertions.
    """

    def __init__(self, queue: Optional[JobQueue] = None) -> None:
        self.queue: JobQueue = queue if queue is not None else InMemoryJobQueue()
        self._contexts: dict[str, AgentTurnContext] = {}
        # MessageTurn bodies keyed by ref. ADR-0105 keeps PII out of the task
        # payload, so the inbound body lives here and the context carries the ref.
        self._message_turns: dict[str, str] = {}

    def _thread_id(self, channel: str, from_identity: str) -> str:
        # CustomerThread: one per stable channel identity. S17: email keys on the
        # From address, SMS on the phone — a phone-shaped key is never written for
        # an email event ((channel, channel_identity) uniqueness, ADR-0115).
        prefix = "email" if is_email_channel(channel) else "textline"
        return f"customer_thread:{prefix}:{from_identity}"

    def _session_id(self, thread_id: str, conversation_id: str) -> str:
        # Session bounded by the 24h window (ADR-0019). The dev store maps one
        # conversation to one session; the real store applies the window. The
        # thread_id prefix already carries the channel, so this key is email-shaped
        # for an email thread without a separate table.
        return f"sms_session:{thread_id}:{conversation_id}"

    def _persist_inbound_turn(
        self, session_id: str, event: InboundChannelEvent
    ) -> str:
        # MessageTurn: one persisted turn per inbound message event.
        ref = f"message_turn:{session_id}:{event.event_id}"
        self._message_turns[ref] = event.body
        return ref

    def persist_accepted_inbound(
        self, decision: InboundDecision
    ) -> tuple[AgentTurnContext, bool]:
        event = decision.event
        if not decision.enqueue or event is None:
            raise ValueError(
                "persist_accepted_inbound requires an accepted (enqueue) decision; "
                f"got action={decision.action!r}."
            )
        created = event.event_id not in self._contexts
        thread_id = self._thread_id(event.channel, event.from_phone)
        session_id = self._session_id(thread_id, event.conversation_id)
        body_ref = self._persist_inbound_turn(session_id, event)
        context = build_agent_turn_context(
            decision,
            sms_session_id=session_id,
            customer_thread_id=thread_id,
            inbound_body_ref=body_ref,
        )
        self._contexts[context.event_id] = context
        if created:
            self.queue.enqueue(to_job_payload(context))
        return context, created

    def load_context(self, event_id: str) -> Optional[AgentTurnContext]:
        return self._contexts.get(event_id)

    def load_inbound_body(self, inbound_body_ref: str) -> Optional[str]:
        return self._message_turns.get(inbound_body_ref)

    def persist_agent_outbound(self, context: AgentTurnContext, body: str) -> None:
        # In-memory substrate: no Workbench read model; keep a ref for tests.
        ref = f"message_turn:{context.sms_session_id}:{context.event_id}:out"
        self._message_turns[ref] = body

    def is_duplicate(self, event_id: str) -> bool:
        return event_id in self._contexts


class InMemoryJobQueue:
    """Records enqueued payloads in order so tests can assert dispatch."""

    def __init__(self) -> None:
        self.payloads: list[AgentJobPayload] = []

    def enqueue(self, payload: AgentJobPayload) -> None:
        self.payloads.append(payload)
