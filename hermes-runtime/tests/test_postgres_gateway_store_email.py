"""S17 live-Postgres: a simulated email lands in Workbench Postgres (FR-18).

Mirrors ``test_postgres_gateway_store`` in the email flavor (skip-if-no-DB via the
shared ``datastore`` fixture): an email ingress event persists an ``email``-channel
thread/case/snapshot, Email Sender Match resolves the From address against the
``identity_link`` graph, and the agent reply mirrors onto the email thread —
webhook-in → reply-in-store seam.
"""

from __future__ import annotations

import json

from starlette.testclient import TestClient

from hermes_runtime.gateway_app import create_app
from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

WEBHOOK_SECRET = "test-simpletexting-url-token"
_FROM = "accounts@acme-fleet.example"



def _email_payload(*, from_address=_FROM, subject="Order 10444", body="Where is my order?",
                   event_id="evt-email-pg", conversation_id="conv-email-pg") -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "conversation_id": conversation_id,
            "from": from_address,
            "subject": subject,
            "body": body,
            "received_at": "2026-01-01T00:00:00Z",
            "type": "email.received",
        }
    ).encode("utf-8")


def _email_decision(*, event_id="evt-email-1", conversation_id="conv-email-1",
                    from_address=_FROM, outcome="unmatched_caller", shopify_id=None):
    from toee_hermes.gateway.ingress import SessionIdentitySnapshot
    from toee_hermes.gateway.normalize import to_inbound_email_event
    from toee_hermes.gateway.pipeline import InboundDecision

    event = to_inbound_email_event(
        event_id=event_id,
        conversation_id=conversation_id,
        from_address=from_address,
        subject="Order 10444",
        body="Where is my order?",
        received_at="2026-01-01T00:00:00Z",
    )
    snapshot = SessionIdentitySnapshot(
        outcome=outcome, resolved_at="2026-01-01T00:00:00Z", shopify_customer_id=shopify_id
    )
    return InboundDecision(status=200, action="enqueue", stage="accept", event=event, snapshot=snapshot)


def _seed_email_link(conn, *, from_address=_FROM, shopify_id="gid://shopify/Customer/1001") -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO identity_link (id, channel, channel_identity, shopify_customer_id, match_status)
            VALUES (%s, 'email', %s, %s, 'verified')
            """,
            ("idl-email-test", from_address, shopify_id),
        )
    conn.commit()


def test_email_persist_creates_email_channel_thread_and_case(datastore) -> None:
    _, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)

    context, created = store.persist_accepted_inbound(_email_decision())
    assert created is True
    assert context.channel == "simulated_email"
    assert context.customer_thread_id == "customer_thread:email:accounts@acme-fleet.example"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT channel, channel_identity FROM customer_thread WHERE id = %s",
            (context.customer_thread_id,),
        )
        assert cur.fetchone() == ("email", _FROM)
        cur.execute(
            "SELECT channel FROM cases WHERE customer_thread_id = %s",
            (context.customer_thread_id,),
        )
        assert cur.fetchone()[0] == "email"
        cur.execute(
            "SELECT channel FROM session_identity_snapshot WHERE event_id = %s",
            ("evt-email-1",),
        )
        assert cur.fetchone()[0] == "email"


def test_email_load_context_round_trips_channel(datastore) -> None:
    _, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    store.persist_accepted_inbound(_email_decision(event_id="evt-email-rt"))

    loaded = store.load_context("evt-email-rt")
    assert loaded is not None
    assert loaded.from_phone == _FROM
    # Persisted vocabulary is "email"; is_email_channel recognizes it (turn binds email).
    from toee_hermes.gateway.normalize import is_email_channel

    assert is_email_channel(loaded.channel)


def test_email_agent_outbound_mirrors_onto_the_email_thread(datastore) -> None:
    _, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    context, _ = store.persist_accepted_inbound(_email_decision(event_id="evt-email-out"))
    store.persist_agent_outbound(context, "Your order 10444 ships tomorrow.")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT direction, author, body FROM message_turn WHERE customer_thread_id = %s AND author = 'hermes'",
            (context.customer_thread_id,),
        )
        assert cur.fetchone() == ("outbound", "hermes", "Your order 10444 ships tomorrow.")


def test_email_webhook_matches_sender_and_persists_verified(datastore) -> None:
    driver, conn, _ = datastore
    _seed_email_link(conn)
    store = PostgresGatewayStore(connection=conn)
    app = create_app(
        webhook_secret=WEBHOOK_SECRET,
        driver=driver,
        store=store,
        is_duplicate=store.is_duplicate,
    )
    client = TestClient(app)
    raw = _email_payload()

    resp = client.post(
        f"/webhooks/simulated-email?token={WEBHOOK_SECRET}", content=raw
    )
    assert resp.status_code == 200

    with conn.cursor() as cur:
        # Email Sender Match resolved the From address to the seeded verified customer.
        cur.execute(
            "SELECT shopify_customer_id, channel FROM customer_thread WHERE channel_identity = %s",
            (_FROM,),
        )
        row = cur.fetchone()
        assert row == ("gid://shopify/Customer/1001", "email")
        cur.execute("SELECT COUNT(*) FROM cases WHERE channel = 'email' AND summary LIKE 'Subject: Order 10444%'")
        assert cur.fetchone()[0] == 1
