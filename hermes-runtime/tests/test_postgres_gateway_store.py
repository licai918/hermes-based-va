"""Postgres GatewayStore: inbound SMS lands in Workbench Postgres (ADR-0140/0142)."""

from __future__ import annotations

import json

from starlette.testclient import TestClient

from hermes_runtime.gateway_app import create_app
from hermes_runtime.postgres_gateway_store import PostgresGatewayStore
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

WEBHOOK_SECRET = "test-simpletexting-url-token"


def _inbound_payload(
    *,
    body: str = "Real inbound from webhook",
    from_phone: str = "+15559876543",
    event_id: str = "evt-pg-1",
) -> bytes:
    return json.dumps(
        {
            "reportId": f"rep-{event_id}",
            "webhookId": "wh-1",
            "type": "INCOMING_MESSAGE",
            "values": {
                "messageId": event_id,
                "text": body,
                "accountPhone": "9053378266",
                "contactPhone": from_phone,
                "timestamp": "2026-01-01T00:00:00.000Z",
                "category": "SMS",
            },
        }
    ).encode("utf-8")


def test_persist_accepted_inbound_creates_workbench_case(datastore) -> None:
    driver, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    from toee_hermes.gateway.ingress import SessionIdentitySnapshot
    from toee_hermes.gateway.normalize import InboundChannelEvent
    from toee_hermes.gateway.pipeline import InboundDecision

    event = InboundChannelEvent(
        channel="simpletexting_sms",
        provider="simpletexting",
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
        channel="simpletexting_sms",
        provider="simpletexting",
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
    driver, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    from toee_hermes.gateway.ingress import SessionIdentitySnapshot
    from toee_hermes.gateway.normalize import InboundChannelEvent
    from toee_hermes.gateway.pipeline import InboundDecision

    event = InboundChannelEvent(
        channel="simpletexting_sms",
        provider="simpletexting",
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
            display_name="Round Trip Customer",
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
    assert loaded.session_identity_snapshot.display_name == "Round Trip Customer"
    assert store.load_inbound_body(persisted.inbound_body_ref) == "Round trip body"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT shopify_customer_id FROM customer_thread WHERE channel_identity = %s",
            ("+15551112222",),
        )
        assert cur.fetchone()[0] == "gid://shopify/Customer/99"
        cur.execute(
            "SELECT match_result FROM session_identity_snapshot WHERE event_id = %s",
            ("evt-rt-1",),
        )
        match_result = cur.fetchone()[0]
    assert match_result["company_name"] == "Round Trip Customer"

    listed = execute_tool(
        tool="toee_workbench_read",
        action="list_cases",
        params={},
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    )
    case = next(c for c in listed.data["cases"] if c["thread_id"] == persisted.customer_thread_id)
    assert case["identity_summary"] == "Verified: Round Trip Customer · +1 (555) 111-2222"


def test_load_customer_memory_returns_slots_for_binding_key(datastore) -> None:
    """S06/FR-1: an indexed read of a binding key's slots, in _render_memory's
    ``[{"slot": ..., "value": ...}, ...]`` shape (no adaptation needed downstream)."""
    _, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    binding_key = "gid://shopify/Customer/2002"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO customer_memory_slot
                (id, binding_key, binding_kind, slot_name, slot_value, source)
            VALUES
                ('mem_test_1', %s, 'verified', 'contact_time_preference', 'mornings', 'customer_explicit'),
                ('mem_test_2', %s, 'verified', 'channel_preference', 'sms', 'customer_explicit')
            """,
            (binding_key, binding_key),
        )

    loaded = store.load_customer_memory(binding_key)

    assert sorted(loaded, key=lambda slot: slot["slot"]) == [
        {"slot": "channel_preference", "value": "sms"},
        {"slot": "contact_time_preference", "value": "mornings"},
    ]
    assert store.load_customer_memory("gid://shopify/Customer/unknown") == []


def test_persist_agent_outbound_writes_hermes_message_turn(datastore) -> None:
    _, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    from toee_hermes.gateway.agent_turn import AgentTurnContext
    from toee_hermes.gateway.ingress import SessionIdentitySnapshot
    from toee_hermes.gateway.normalize import InboundChannelEvent
    from toee_hermes.gateway.pipeline import InboundDecision

    event = InboundChannelEvent(
        channel="simpletexting_sms",
        provider="simpletexting",
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


def test_persist_agent_outbound_is_idempotent_per_turn(datastore) -> None:
    """A re-dispatched turn must not double-write the same hermes reply."""
    _, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    from toee_hermes.gateway.ingress import SessionIdentitySnapshot
    from toee_hermes.gateway.normalize import InboundChannelEvent
    from toee_hermes.gateway.pipeline import InboundDecision

    event = InboundChannelEvent(
        channel="simpletexting_sms",
        provider="simpletexting",
        event_id="evt-out-idem",
        conversation_id="conv-out-idem",
        from_phone="+15559876543",
        body="Need help",
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
    store.persist_agent_outbound(context, "Reply once.")
    store.persist_agent_outbound(context, "Reply once.")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM message_turn WHERE customer_thread_id = %s AND author = 'hermes'",
            (context.customer_thread_id,),
        )
        assert cur.fetchone()[0] == 1


def test_webhook_through_create_app_writes_case(datastore) -> None:
    driver, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    app = create_app(
        webhook_secret=WEBHOOK_SECRET,
        driver=driver,
        store=store,
        is_duplicate=store.is_duplicate,
    )
    client = TestClient(app)
    raw = _inbound_payload(body="Real inbound from webhook")

    response = client.post(
        f"/webhooks/simpletexting?token={WEBHOOK_SECRET}",
        content=raw,
    )

    assert response.status_code == 200
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM cases WHERE summary LIKE 'Real inbound%'"
        )
        assert cur.fetchone()[0] == 1


def _job_count(conn, event_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM job WHERE payload->>'event_id' = %s", (event_id,)
        )
        return cur.fetchone()[0]


def test_is_duplicate_skips_second_enqueue(datastore) -> None:
    """A redelivery must not add a second turn job. The count is read off the
    durable ``job`` table, because since S02 fix wave 1 the enqueue happens inside
    ``persist_accepted_inbound``'s transaction -- there is no queue seam on the
    route to observe instead."""
    driver, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    app = create_app(
        webhook_secret=WEBHOOK_SECRET,
        driver=driver,
        store=store,
        is_duplicate=store.is_duplicate,
    )
    client = TestClient(app)
    raw = _inbound_payload(event_id="evt-dup-1")

    assert client.post(
        f"/webhooks/simpletexting?token={WEBHOOK_SECRET}",
        content=raw,
    ).status_code == 200
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM agent_turn_context WHERE event_id = %s", ("evt-dup-1",))
        assert cur.fetchone()[0] == 1
    assert _job_count(conn, "evt-dup-1") == 1

    assert client.post(
        f"/webhooks/simpletexting?token={WEBHOOK_SECRET}",
        content=raw,
    ).status_code == 200
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM agent_turn_context WHERE event_id = %s", ("evt-dup-1",))
        assert cur.fetchone()[0] == 1
    assert _job_count(conn, "evt-dup-1") == 1


def test_claim_event_is_atomic_and_survives_a_new_store_instance(datastore) -> None:
    # ADR-0016 exactly-once, durably: the opt-out branch persists no context, so
    # its idempotency lives in inbound_event_claim. A second claim must lose even
    # from a fresh store object (i.e. another Cloud Run instance / after restart).
    _, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)

    assert store.claim_event("evt-optout-1") is True
    assert store.claim_event("evt-optout-1") is False
    assert store.is_duplicate("evt-optout-1") is True

    other_instance = PostgresGatewayStore(connection=conn)
    assert other_instance.claim_event("evt-optout-1") is False


def test_replayed_opt_out_sends_one_confirmation_through_postgres(datastore) -> None:
    # The full route against the durable store: five verbatim replays of a tokened
    # STOP webhook must yield exactly one outbound SMS.
    driver, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    sent: list[tuple[str, str]] = []
    app = create_app(
        webhook_secret=WEBHOOK_SECRET,
        driver=driver,
        store=store,
        is_duplicate=store.is_duplicate,
        reply_sender=lambda conversation_id, text: sent.append((conversation_id, text)),
    )
    client = TestClient(app)
    raw = _inbound_payload(body="STOP", event_id="evt-optout-replay")

    codes = [
        client.post(
            f"/webhooks/simpletexting?token={WEBHOOK_SECRET}", content=raw
        ).status_code
        for _ in range(5)
    ]

    assert codes == [200] * 5
    assert len(sent) == 1
