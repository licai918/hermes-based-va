"""Postgres GatewayStore: inbound SMS lands in Workbench Postgres (ADR-0140/0142)."""

from __future__ import annotations

import hashlib
import hmac
import json

from starlette.testclient import TestClient

from hermes_runtime.gateway_app import create_app
from hermes_runtime.gateway_store import InMemoryJobQueue
from hermes_runtime.job_dispatch import LocalDispatchingJobQueue
from hermes_runtime.postgres_gateway_store import PostgresGatewayStore
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

WEBHOOK_SECRET = "test-textline-shared-secret"
SIGNATURE_HEADER = "X-Textline-Signature"


def _sign(raw_body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()


def _inbound_payload(
    *,
    body: str = "Real inbound from webhook",
    from_phone: str = "+15559876543",
    event_id: str = "evt-pg-1",
    conversation_id: str = "conv-pg-1",
) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "conversation_id": conversation_id,
            "from": from_phone,
            "body": body,
            "received_at": "2026-01-01T00:00:00Z",
            "type": "message.created",
        }
    ).encode("utf-8")


def test_persist_accepted_inbound_creates_workbench_case(datastore) -> None:
    driver, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    from toee_hermes.gateway.ingress import SessionIdentitySnapshot
    from toee_hermes.gateway.normalize import InboundChannelEvent
    from toee_hermes.gateway.pipeline import InboundDecision

    event = InboundChannelEvent(
        channel="textline_sms",
        provider="textline",
        event_id="evt-case-1",
        conversation_id="conv-case-1",
        from_phone="+15559876543",
        body="Where is my order 10444?",
        received_at="2026-01-01T00:00:00Z",
        raw_event_type="message.created",
        media_urls=None,
    )
    decision = InboundDecision(
        status=200,
        action="enqueue",
        stage="accept",
        event=event,
        snapshot=SessionIdentitySnapshot(
            outcome="unmatched_caller", resolved_at="2026-01-01T00:00:00Z"
        ),
    )

    context, created = store.persist_accepted_inbound(decision)
    assert created is True
    assert context.event_id == "evt-case-1"

    listed = execute_tool(
        tool="toee_workbench_read",
        action="list_cases",
        params={},
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    )
    assert any(
        c["thread_id"] == context.customer_thread_id for c in listed.data["cases"]
    )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT body FROM message_turn WHERE id = %s",
            (context.inbound_body_ref,),
        )
        assert cur.fetchone()[0] == "Where is my order 10444?"


def test_persist_is_idempotent_on_duplicate_event_id(datastore) -> None:
    _, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    from toee_hermes.gateway.normalize import InboundChannelEvent
    from toee_hermes.gateway.pipeline import InboundDecision

    event = InboundChannelEvent(
        channel="textline_sms",
        provider="textline",
        event_id="evt-idem-1",
        conversation_id="conv-idem-1",
        from_phone="+15559876543",
        body="First message",
        received_at="2026-01-01T00:00:00Z",
        raw_event_type="message.created",
        media_urls=None,
    )
    decision = InboundDecision(
        status=200,
        action="enqueue",
        stage="accept",
        event=event,
        snapshot=None,
    )

    _, created_first = store.persist_accepted_inbound(decision)
    _, created_second = store.persist_accepted_inbound(decision)
    assert created_first is True
    assert created_second is False

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM agent_turn_context WHERE event_id = %s",
            ("evt-idem-1",),
        )
        assert cur.fetchone()[0] == 1


def test_load_context_and_inbound_body_round_trip(datastore) -> None:
    _, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    from toee_hermes.gateway.ingress import SessionIdentitySnapshot
    from toee_hermes.gateway.normalize import InboundChannelEvent
    from toee_hermes.gateway.pipeline import InboundDecision

    event = InboundChannelEvent(
        channel="textline_sms",
        provider="textline",
        event_id="evt-rt-1",
        conversation_id="conv-rt-1",
        from_phone="+15551112222",
        body="Round trip body",
        received_at="2026-01-01T00:00:00Z",
        raw_event_type="message.created",
        media_urls=None,
    )
    decision = InboundDecision(
        status=200,
        action="enqueue",
        stage="accept",
        event=event,
        snapshot=SessionIdentitySnapshot(
            outcome="verified_customer",
            resolved_at="2026-01-01T00:00:00Z",
            shopify_customer_id="gid://shopify/Customer/99",
        ),
    )

    persisted, _ = store.persist_accepted_inbound(decision)
    loaded = store.load_context("evt-rt-1")

    assert loaded is not None
    assert loaded.event_id == persisted.event_id
    assert loaded.conversation_id == "conv-rt-1"
    assert loaded.from_phone == "+15551112222"
    assert loaded.inbound_body_ref == persisted.inbound_body_ref
    assert loaded.session_identity_snapshot is not None
    assert loaded.session_identity_snapshot.outcome == "verified_customer"
    assert store.load_inbound_body(persisted.inbound_body_ref) == "Round trip body"


def test_persist_agent_outbound_writes_hermes_message_turn(datastore) -> None:
    _, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    from toee_hermes.gateway.agent_turn import AgentTurnContext
    from toee_hermes.gateway.ingress import SessionIdentitySnapshot
    from toee_hermes.gateway.normalize import InboundChannelEvent
    from toee_hermes.gateway.pipeline import InboundDecision

    event = InboundChannelEvent(
        channel="textline_sms",
        provider="textline",
        event_id="evt-out-1",
        conversation_id="conv-out-1",
        from_phone="+15559876543",
        body="Need help with tires",
        received_at="2026-01-01T00:00:00Z",
        raw_event_type="message.created",
        media_urls=None,
    )
    decision = InboundDecision(
        status=200,
        action="enqueue",
        stage="accept",
        event=event,
        snapshot=SessionIdentitySnapshot(
            outcome="unmatched_caller", resolved_at="2026-01-01T00:00:00Z"
        ),
    )
    context, _ = store.persist_accepted_inbound(decision)
    store.persist_agent_outbound(context, "We have 225/65R17 in stock.")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT direction, author, body FROM message_turn
            WHERE customer_thread_id = %s AND author = 'hermes'
            """,
            (context.customer_thread_id,),
        )
        row = cur.fetchone()
    assert row == ("outbound", "hermes", "We have 225/65R17 in stock.")


def test_webhook_through_create_app_writes_case(datastore) -> None:
    driver, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    app = create_app(
        webhook_secret=WEBHOOK_SECRET,
        driver=driver,
        store=store,
        queue=LocalDispatchingJobQueue(store=store, turn_runner=lambda *_: None),
        is_duplicate=store.is_duplicate,
    )
    client = TestClient(app)
    raw = _inbound_payload(body="Real inbound from webhook")

    response = client.post(
        "/webhooks/textline",
        content=raw,
        headers={SIGNATURE_HEADER: _sign(raw)},
    )

    assert response.status_code == 200
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM cases WHERE summary LIKE 'Real inbound%'"
        )
        assert cur.fetchone()[0] == 1


def test_is_duplicate_skips_second_enqueue(datastore) -> None:
    driver, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    queue = InMemoryJobQueue()
    app = create_app(
        webhook_secret=WEBHOOK_SECRET,
        driver=driver,
        store=store,
        queue=queue,
        is_duplicate=store.is_duplicate,
    )
    client = TestClient(app)
    raw = _inbound_payload(event_id="evt-dup-1")

    assert client.post(
        "/webhooks/textline",
        content=raw,
        headers={SIGNATURE_HEADER: _sign(raw)},
    ).status_code == 200
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM agent_turn_context WHERE event_id = %s", ("evt-dup-1",))
        assert cur.fetchone()[0] == 1
    assert len(queue.payloads) == 1

    assert client.post(
        "/webhooks/textline",
        content=raw,
        headers={SIGNATURE_HEADER: _sign(raw)},
    ).status_code == 200
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM agent_turn_context WHERE event_id = %s", ("evt-dup-1",))
        assert cur.fetchone()[0] == 1
    assert len(queue.payloads) == 1
