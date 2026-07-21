"""S17: the simulated-email webhook drives the same governed turn + reply (FR-18).

Mirrors ``test_gateway_app``'s ``test_webhook_alone_drives_the_reply_through_the_
local_dispatcher`` in the email flavor: a single signed POST to
``/webhooks/simulated-email`` fast-acks and the in-process dispatcher runs the bound
External turn, deriving + delivering the reply through the S01 reply-sender gate.
The email reply is NOT SMS-clipped (RK-4 / constraint d).
"""

from __future__ import annotations

import json

from starlette.testclient import TestClient

from hermes_runtime.gateway_app import create_app
from hermes_runtime.gateway_store import InMemoryGatewayStore
from hermes_runtime.job_dispatch import LocalDispatchingJobQueue
from hermes_runtime.turn_runner import make_gateway_turn_runner, run_gateway_turn

WEBHOOK_SECRET = "test-simpletexting-url-token"
JOB_SECRET = "test-internal-job-secret"



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


def test_simulated_email_webhook_drives_the_reply_and_does_not_clip() -> None:
    store = InMemoryGatewayStore()
    sent: list[tuple[str, str]] = []
    mirrored: list[tuple[str, str]] = []
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
        on_reply_sent=lambda ctx, text: mirrored.append((ctx.conversation_id, text)),
    )
    app = create_app(
        webhook_secret=WEBHOOK_SECRET,
        internal_job_secret=JOB_SECRET,
        store=store,
        queue=LocalDispatchingJobQueue(
            store=store, turn_runner=turn_runner, dispatch=lambda work: work()
        ),
        turn_runner=turn_runner,
    )
    client = TestClient(app)
    raw = _email_payload()

    resp = client.post(
        f"/webhooks/simulated-email?token={WEBHOOK_SECRET}", content=raw
    )
    assert resp.status_code == 200
    # Email delivery is the mirror, not the SMS provider: reply_sender is the live
    # SimpleTexting client and strips its argument to digits, so an email turn must
    # never reach it (RK-4 — there is no email provider; ADR-0153).
    assert sent == []
    assert mirrored == [("conv-email", reply_body)]

    # The outbound reply mirrored onto the EMAIL thread/session, not a phone-shaped key.
    context = store.load_context("evt-email")
    assert context is not None
    assert context.channel == "simulated_email"
    assert context.customer_thread_id == "customer_thread:email:accounts@acme-fleet.example"


def test_simulated_email_webhook_rejects_a_forged_token() -> None:
    app = create_app(webhook_secret=WEBHOOK_SECRET)
    client = TestClient(app)
    raw = _email_payload()
    resp = client.post(
        "/webhooks/simulated-email?token=deadbeef", content=raw
    )
    assert resp.status_code == 401
