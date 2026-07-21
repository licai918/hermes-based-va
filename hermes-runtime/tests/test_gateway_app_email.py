"""S17: the simulated-email webhook drives the same governed turn + reply (FR-18).

A single signed POST to ``/webhooks/simulated-email`` fast-acks and enqueues via
``store.queue``. In production that is the durable Postgres queue the separate
turn-worker process claims (0.0.4 S02, ADR-0153); here a test-only
``_InlineTurnQueue`` runs the same shared ``execute_agent_turn_job`` inline instead,
so the test stays DB-free and synchronous while covering the S17 email-channel
binding (subject folded into the turn body, reply mirrored onto the email thread
key), not the queue substrate. The email reply is NOT SMS-clipped (RK-4 /
constraint d).
"""

from __future__ import annotations

import hashlib
import hmac
import json

from starlette.testclient import TestClient

from hermes_runtime.agent_turn_job import execute_agent_turn_job
from hermes_runtime.gateway_app import create_app
from hermes_runtime.gateway_store import InMemoryGatewayStore
from hermes_runtime.turn_runner import make_gateway_turn_runner, run_gateway_turn

WEBHOOK_SECRET = "test-textline-shared-secret"
SIGNATURE_HEADER = "X-Textline-Signature"
JOB_SECRET = "test-internal-job-secret"


def _sign(raw_body: bytes) -> str:
    return hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def _email_payload(*, from_address="accounts@acme-fleet.example", subject="Order 10444",
                   body="Where is my order?", event_id="evt-email", conversation_id="conv-email") -> bytes:
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


class _InlineTurnQueue:
    """Test-only ``JobQueue`` that runs the shared bound-turn job body inline.

    Production writes a durable row inside the store's persist transaction and the
    turn-worker process claims it (0.0.4 S02, ADR-0153); this test is about the S17
    email channel binding, not the substrate, so running the job body inline keeps
    it synchronous and DB-free. Injected into the store, which is where the enqueue
    lives now.
    """

    def __init__(self, *, store, turn_runner) -> None:
        self._store = store
        self._turn_runner = turn_runner

    def enqueue(self, payload) -> None:
        execute_agent_turn_job(
            store=self._store, turn_runner=self._turn_runner, payload=payload
        )


def test_simulated_email_webhook_drives_the_reply_and_does_not_clip() -> None:
    store = InMemoryGatewayStore()
    sent: list[tuple[str, str]] = []
    # A reply longer than the SMS single-segment cap (480): an email must deliver it
    # in full (never clip_sms_reply'd). No trailing whitespace, so the delivered
    # text is byte-identical to the model's final_response.
    reply_body = "Thanks for reaching out about order 10444. " + ("Detail. " * 80) + "End."
    assert len(reply_body) > 480

    def run_turn(context, inbound_body):
        # The subject was folded into the turn body upstream (S17): prove the turn
        # sees it, so nothing is dropped.
        assert "Subject: Order 10444" in inbound_body
        return run_gateway_turn(
            conversation_id=context.conversation_id,
            inbound_body=inbound_body,
            system_message="You are Toee Tire support.",
            scripted_completions=[{"content": reply_body}],
        )

    turn_runner = make_gateway_turn_runner(
        reply_sender=lambda conv, text: sent.append((conv, text)),
        run_turn=run_turn,
    )
    # The inline queue needs the turn runner, which needs the store -- so it is
    # attached after construction rather than passed to __init__.
    store.queue = _InlineTurnQueue(store=store, turn_runner=turn_runner)
    app = create_app(
        webhook_secret=WEBHOOK_SECRET,
        internal_job_secret=JOB_SECRET,
        store=store,
        turn_runner=turn_runner,
    )
    client = TestClient(app)
    raw = _email_payload()

    resp = client.post(
        "/webhooks/simulated-email", content=raw, headers={SIGNATURE_HEADER: _sign(raw)}
    )
    assert resp.status_code == 200
    assert sent == [("conv-email", reply_body)]

    # The outbound reply mirrored onto the EMAIL thread/session, not a phone-shaped key.
    context = store.load_context("evt-email")
    assert context is not None
    assert context.channel == "simulated_email"
    assert context.customer_thread_id == "customer_thread:email:accounts@acme-fleet.example"


def test_simulated_email_webhook_rejects_a_forged_signature() -> None:
    app = create_app(webhook_secret=WEBHOOK_SECRET)
    client = TestClient(app)
    raw = _email_payload()
    resp = client.post(
        "/webhooks/simulated-email", content=raw, headers={SIGNATURE_HEADER: "deadbeef"}
    )
    assert resp.status_code == 401
