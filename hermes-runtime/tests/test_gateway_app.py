"""Textline gateway HTTP surface (ADR-0095 Python-native, ADR-0021/0104).

The FastAPI app lives in the embedding venv (never in deps-free toee-hermes) and
wraps the pure ``toee_hermes.gateway.*`` decision logic. G1 pins the first line of
defense: every inbound webhook must carry a valid HMAC-SHA256 body signature
(ADR-0021) or be rejected with 401 before any processing (ADR-0104).
"""

from __future__ import annotations

import hashlib
import hmac
import json

from starlette.testclient import TestClient

from hermes_runtime.gateway_app import (
    INTERNAL_JOB_SECRET_HEADER,
    create_app,
)
from hermes_runtime.gateway_store import InMemoryGatewayStore, InMemoryJobQueue
from hermes_runtime.turn_runner import make_gateway_turn_runner, run_gateway_turn
from toee_hermes.gateway.opt_out import SMS_OPT_OUT_CONFIRMATION

WEBHOOK_SECRET = "test-textline-shared-secret"
SIGNATURE_HEADER = "X-Textline-Signature"
JOB_SECRET = "test-internal-job-secret"


def _sign(raw_body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()


def _inbound_payload(
    *,
    body: str,
    from_phone: str = "+15551230000",
    event_id: str = "evt-1",
    conversation_id: str = "conv-1",
) -> bytes:
    """Build a v1 Textline inbound webhook JSON body (route-layer schema)."""
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


def _post_signed(client: TestClient, raw: bytes):
    return client.post(
        "/webhooks/textline", content=raw, headers={SIGNATURE_HEADER: _sign(raw)}
    )


def test_webhook_rejects_request_without_a_valid_signature() -> None:
    client = TestClient(create_app(webhook_secret=WEBHOOK_SECRET))
    raw = b'{"event":"message.created"}'

    response = client.post(
        "/webhooks/textline",
        content=raw,
        headers={SIGNATURE_HEADER: "deadbeef-not-a-valid-hmac"},
    )

    assert response.status_code == 401


def test_webhook_accepts_a_request_signed_with_the_shared_secret() -> None:
    client = TestClient(create_app(webhook_secret=WEBHOOK_SECRET))
    raw = b'{"event":"message.created"}'

    response = client.post(
        "/webhooks/textline",
        content=raw,
        headers={SIGNATURE_HEADER: _sign(raw)},
    )

    assert response.status_code == 200


def test_opt_out_inbound_acks_200_and_sends_one_fixed_confirmation() -> None:
    # ADR-0108/0016: an opt-out keyword short-circuits the agent pipeline; the
    # gateway acks 200 and sends exactly one fixed confirmation to the thread.
    sent: list[tuple[str, str]] = []
    app = create_app(
        webhook_secret=WEBHOOK_SECRET,
        reply_sender=lambda conversation_id, text: sent.append((conversation_id, text)),
    )
    client = TestClient(app)
    raw = _inbound_payload(body="STOP", conversation_id="conv-optout")

    response = _post_signed(client, raw)

    assert response.status_code == 200
    assert sent == [("conv-optout", SMS_OPT_OUT_CONFIRMATION)]


def test_normal_inbound_acks_200_without_sending_a_compliance_reply() -> None:
    # A non-opt-out inbound is acked (ADR-0103 fast-ack); the gateway sends no
    # compliance reply itself — the agent turn (enqueued) owns any response.
    sent: list[tuple[str, str]] = []
    app = create_app(
        webhook_secret=WEBHOOK_SECRET,
        reply_sender=lambda conversation_id, text: sent.append((conversation_id, text)),
    )
    client = TestClient(app)
    raw = _inbound_payload(
        body="Do you have 225/65R17 in stock?", from_phone="+14165550101"
    )

    response = _post_signed(client, raw)

    assert response.status_code == 200
    assert sent == []


def test_accepted_inbound_persists_context_and_enqueues_one_job() -> None:
    # ADR-0105/0107: an accepted turn is persisted (memory is the source of truth)
    # and a minimal job (eventId + conversationId) is enqueued for the async run.
    store = InMemoryGatewayStore()
    queue = InMemoryJobQueue()
    app = create_app(webhook_secret=WEBHOOK_SECRET, store=store, queue=queue)
    client = TestClient(app)
    raw = _inbound_payload(
        body="Do you have 225/65R17 in stock?",
        from_phone="+14165550101",
        event_id="evt-accept",
        conversation_id="conv-accept",
    )

    response = _post_signed(client, raw)

    assert response.status_code == 200
    assert [(p.event_id, p.conversation_id) for p in queue.payloads] == [
        ("evt-accept", "conv-accept")
    ]
    context = store.load_context("evt-accept")
    assert context is not None
    assert context.conversation_id == "conv-accept"
    assert context.from_phone == "+14165550101"
    assert context.session_identity_snapshot is not None
    assert context.session_identity_snapshot.outcome == "verified_customer"
    # ADR-0115 hierarchy: thread per channel identity, session per window, and an
    # inbound MessageTurn reference (the body is stored, not in the task payload).
    assert context.customer_thread_id
    assert context.sms_session_id
    assert context.inbound_body_ref


def test_opt_out_inbound_persists_no_context_and_enqueues_nothing() -> None:
    # Only accepted (enqueue) decisions start a turn (ADR-0115): opt-out persists no
    # AgentTurnContext and enqueues no job.
    store = InMemoryGatewayStore()
    queue = InMemoryJobQueue()
    app = create_app(webhook_secret=WEBHOOK_SECRET, store=store, queue=queue)
    client = TestClient(app)
    raw = _inbound_payload(
        body="STOP", event_id="evt-stop", conversation_id="conv-stop"
    )

    response = _post_signed(client, raw)

    assert response.status_code == 200
    assert queue.payloads == []
    assert store.load_context("evt-stop") is None


def test_internal_agent_turn_requires_the_internal_job_secret() -> None:
    # ADR-0106: /internal/jobs/agent-turn is not a public surface. Without the
    # configured shared secret (local-dev auth) it returns 401 and runs nothing.
    runs: list[str] = []
    app = create_app(
        webhook_secret=WEBHOOK_SECRET,
        internal_job_secret=JOB_SECRET,
        turn_runner=lambda context, body: runs.append(context.event_id),
    )
    client = TestClient(app)

    response = client.post(
        "/internal/jobs/agent-turn",
        content=json.dumps({"event_id": "evt-x", "conversation_id": "conv-x"}),
    )

    assert response.status_code == 401
    assert runs == []


def test_internal_agent_turn_runs_the_turn_for_a_matching_authed_job() -> None:
    # End-to-end: a webhook persists + enqueues, then the internal job route reloads
    # the context by eventId, verifies the binding (ADR-0107), and runs the turn
    # with the loaded session context and inbound body.
    store = InMemoryGatewayStore()
    queue = InMemoryJobQueue()
    runs: list[tuple[str, str, str]] = []
    app = create_app(
        webhook_secret=WEBHOOK_SECRET,
        internal_job_secret=JOB_SECRET,
        store=store,
        queue=queue,
        turn_runner=lambda context, body: runs.append(
            (context.event_id, context.conversation_id, body)
        ),
    )
    client = TestClient(app)
    raw = _inbound_payload(
        body="Where is my order?",
        from_phone="+14165550101",
        event_id="evt-turn",
        conversation_id="conv-turn",
    )
    assert _post_signed(client, raw).status_code == 200
    payload = queue.payloads[0]

    response = client.post(
        "/internal/jobs/agent-turn",
        content=json.dumps(
            {"event_id": payload.event_id, "conversation_id": payload.conversation_id}
        ),
        headers={INTERNAL_JOB_SECRET_HEADER: JOB_SECRET},
    )

    assert response.status_code == 200
    assert runs == [("evt-turn", "conv-turn", "Where is my order?")]


def test_internal_agent_turn_404_when_context_is_unknown() -> None:
    # Memory is the source of truth (ADR-0107): an eventId with no persisted context
    # cannot run a turn.
    runs: list[str] = []
    app = create_app(
        webhook_secret=WEBHOOK_SECRET,
        internal_job_secret=JOB_SECRET,
        turn_runner=lambda context, body: runs.append(context.event_id),
    )
    client = TestClient(app)

    response = client.post(
        "/internal/jobs/agent-turn",
        content=json.dumps({"event_id": "missing", "conversation_id": "conv-x"}),
        headers={INTERNAL_JOB_SECRET_HEADER: JOB_SECRET},
    )

    assert response.status_code == 404
    assert runs == []


def test_internal_agent_turn_runs_a_real_bound_turn_and_delivers_the_reply() -> None:
    # Full loop (ADR-0103/0105/0106/0107): signed webhook -> persist + enqueue ->
    # internal job -> a real bound governed AIAgent turn -> the governed Textline
    # reply is derived and delivered to the inbound turn's conversation. The model
    # is the only fake (scripted provider); the agent loop, governed dispatch, and
    # turn binding are all real.
    store = InMemoryGatewayStore()
    queue = InMemoryJobQueue()
    sent: list[tuple[str, str]] = []
    reply_body = "Your order TOEE-1001 shipped today - tracking to follow."

    def run_turn(context, inbound_body):
        return run_gateway_turn(
            conversation_id=context.conversation_id,
            inbound_body=inbound_body,
            system_message="You are Toee Tire support.",
            scripted_completions=[
                {
                    "tool_calls": [
                        {
                            "name": "toee_textline_reply__send_message",
                            "arguments": {
                                "conversation_id": context.conversation_id,
                                "body": reply_body,
                            },
                        }
                    ]
                },
                {"content": "Done - I've texted you the update."},
            ],
        )

    app = create_app(
        webhook_secret=WEBHOOK_SECRET,
        internal_job_secret=JOB_SECRET,
        store=store,
        queue=queue,
        turn_runner=make_gateway_turn_runner(
            reply_sender=lambda conv, text: sent.append((conv, text)),
            run_turn=run_turn,
        ),
    )
    client = TestClient(app)
    raw = _inbound_payload(
        body="Where is my order?",
        from_phone="+14165550101",
        event_id="evt-e2e",
        conversation_id="conv-e2e",
    )
    assert _post_signed(client, raw).status_code == 200
    payload = queue.payloads[0]

    response = client.post(
        "/internal/jobs/agent-turn",
        content=json.dumps(
            {"event_id": payload.event_id, "conversation_id": payload.conversation_id}
        ),
        headers={INTERNAL_JOB_SECRET_HEADER: JOB_SECRET},
    )

    assert response.status_code == 200
    assert sent == [("conv-e2e", reply_body)]
