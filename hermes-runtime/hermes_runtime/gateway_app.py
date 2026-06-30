"""Textline gateway HTTP surface (ADR-0095 Python-native, ADR-0103/0104/0108).

The FastAPI app that wraps the pure ``toee_hermes.gateway.*`` decision logic and
(later) the embedded AIAgent turn. It lives in the embedding venv, never in
deps-free ``toee-hermes`` (ADR-0096/0100): only this layer and the plugin may pull
heavy dependencies or import Hermes.

The webhook route is intentionally thin (ADR-0103 fast-ack): parse the provider
body, run the deterministic :func:`process_inbound` decision, send the one fixed
opt-out confirmation when required (ADR-0108/0016), and map the decision status to
the HTTP response (verify=401, transient ingress=500, everything else=200).
Persistence and the async agent turn are layered on in later slices.
"""

from __future__ import annotations

import hmac
import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from fastapi import FastAPI, Request, Response

from toee_hermes.drivers.mock import MockDriver, create_all_mock_handlers
from toee_hermes.execute import ToolDriver
from toee_hermes.gateway.agent_turn import (
    AgentJobPayload,
    AgentTurnContext,
    to_job_payload,
)
from toee_hermes.gateway.normalize import TextlineInboundFields
from toee_hermes.gateway.pipeline import DuplicateCheck, process_inbound
from toee_hermes.gateway.rate_limit import (
    InboundRateLimiter,
    create_inbound_rate_limiter,
)

from hermes_runtime.agent_turn_job import AgentJobOutcome, execute_agent_turn_job
from hermes_runtime.gateway_store import (
    GatewayStore,
    InMemoryGatewayStore,
    InMemoryJobQueue,
    JobQueue,
)

# Provider signature headers (ADR-0021). Live Textline (TGP) uses X-Tgp-*; local
# simulate script uses the legacy X-Textline-Signature flat JSON shape.
TGP_SIGNATURE_HEADER = "X-Tgp-Event-Signature"
TGP_EVENT_TIME_HEADER = "X-Tgp-Event-Time"
TGP_EVENT_TYPE_HEADER = "X-Tgp-Event-Type"
LEGACY_SIGNATURE_HEADER = "X-Textline-Signature"

# Local-dev shared-secret header for the internal agent-turn route (ADR-0106).
# Production verifies Cloud Tasks OIDC upstream instead.
INTERNAL_JOB_SECRET_HEADER = "X-Internal-Job-Secret"

# Sends a gateway-level (non-agent) reply to a conversation thread — used for the
# fixed opt-out confirmation, which must bypass the agent turn (ADR-0108/0016).
# The deployment wiring injects a real Textline client; tests inject a fake.
ReplySender = Callable[[str, str], None]

# Runs one async agent turn for a reloaded context against its inbound body. The
# production runner boots the External profile agent with the loaded session
# context and replies via governed toee_textline_reply (ADR-0107); tests inject a
# fake. run_live_turn is the eval harness, not this production seam.
TurnRunner = Callable[[AgentTurnContext, str], None]

# resolved_at clock for the Session Identity Snapshot (injectable for determinism).
Clock = Callable[[], str]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_from_unix_ts(value: Any) -> str:
    if value is None:
        return ""
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return str(value)
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_tgp_new_customer_post(payload: dict[str, Any]) -> TextlineInboundFields:
    post = payload.get("post") if isinstance(payload.get("post"), dict) else {}
    conversation = (
        payload.get("conversation") if isinstance(payload.get("conversation"), dict) else {}
    )
    creator = post.get("creator") if isinstance(post.get("creator"), dict) else {}
    customer = (
        conversation.get("customer")
        if isinstance(conversation.get("customer"), dict)
        else {}
    )
    attachments = post.get("attachments")
    media_urls: Optional[list[str]] = None
    if isinstance(attachments, list):
        urls = [
            str(item.get("url"))
            for item in attachments
            if isinstance(item, dict) and item.get("url")
        ]
        media_urls = urls or None
    from_phone = str(creator.get("phone_number") or customer.get("phone_number") or "")
    conversation_id = str(
        post.get("conversation_uuid") or conversation.get("uuid") or ""
    )
    return TextlineInboundFields(
        event_id=str(post.get("uuid", "")),
        conversation_id=conversation_id,
        from_phone=from_phone,
        body=str(post.get("body", "")),
        received_at=_iso_from_unix_ts(post.get("created_at")),
        raw_event_type="new_customer_post",
        media_urls=media_urls,
    )


def is_ignored_tgp_webhook(payload: dict[str, Any]) -> bool:
    """Non-customer TGP posts ack 200 without agent work (ADR-0102)."""
    if payload.get("webhook") != "new_customer_post":
        return False
    post = payload.get("post") if isinstance(payload.get("post"), dict) else {}
    if post.get("is_whisper"):
        return True
    creator = post.get("creator") if isinstance(post.get("creator"), dict) else {}
    return creator.get("type") != "customer"


def parse_textline_fields(payload: dict[str, Any]) -> TextlineInboundFields:
    """Map Textline webhook JSON onto canonical inbound fields (ADR-0102).

    Supports live TGP ``new_customer_post`` webhooks and the legacy flat JSON used
    by ``scripts/simulate-textline-webhook.ps1``.
    """
    if payload.get("webhook") == "new_customer_post":
        return _parse_tgp_new_customer_post(payload)
    media = payload.get("media_urls")
    return TextlineInboundFields(
        event_id=str(payload.get("id", "")),
        conversation_id=str(payload.get("conversation_id", "")),
        from_phone=str(payload.get("from", "")),
        body=str(payload.get("body", "")),
        received_at=str(payload.get("received_at", "")),
        raw_event_type=str(payload.get("type", "")),
        media_urls=list(media) if isinstance(media, list) else None,
    )


def _webhook_signature_context(
    request: Request,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    signature = request.headers.get(TGP_SIGNATURE_HEADER) or request.headers.get(
        LEGACY_SIGNATURE_HEADER
    )
    event_time = request.headers.get(TGP_EVENT_TIME_HEADER)
    event_type = request.headers.get(TGP_EVENT_TYPE_HEADER)
    return signature, event_time, event_type


def _never_duplicate(event_id: str) -> bool:
    return False


def create_app(
    *,
    webhook_secret: str,
    driver: Optional[ToolDriver] = None,
    rate_limiter: Optional[InboundRateLimiter] = None,
    reply_sender: Optional[ReplySender] = None,
    is_duplicate: Optional[DuplicateCheck] = None,
    clock: Optional[Clock] = None,
    store: Optional[GatewayStore] = None,
    queue: Optional[JobQueue] = None,
    internal_job_secret: Optional[str] = None,
    turn_runner: Optional[TurnRunner] = None,
) -> FastAPI:
    """Build the Textline gateway app from its injected collaborators.

    Defaults are mock-first (ADR-0137) and in-memory (ADR-0140 dev substrate): an
    unconfigured app boots against the mock driver, a fresh in-process rate limiter,
    and an in-memory store/queue. The deployment composition root injects the
    resolved integration driver, the durable idempotency check, the real Textline
    reply client, and the Postgres-backed store and Cloud Tasks queue.
    """
    driver = driver or MockDriver(create_all_mock_handlers())
    rate_limiter = rate_limiter or create_inbound_rate_limiter()
    is_duplicate = is_duplicate or _never_duplicate
    clock = clock or _utc_now_iso
    store = store or InMemoryGatewayStore()
    queue = queue or InMemoryJobQueue()

    app = FastAPI()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        # Cheap liveness probe for the Cloud Run health check (ADR-0098, issue #33):
        # no secret, store, or turn-runner dependency, so it answers before (and
        # independently of) any inbound traffic. Readiness of the model/Textline
        # connections is enforced at boot by build_gateway_app (fail-closed).
        return {"status": "ok"}

    @app.post("/webhooks/textline")
    async def textline_webhook(request: Request) -> Response:
        raw = await request.body()
        raw_text = raw.decode("utf-8")
        signature, event_time, event_type = _webhook_signature_context(request)
        try:
            payload = json.loads(raw_text) if raw_text else {}
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        if is_ignored_tgp_webhook(payload):
            return Response(status_code=200)

        decision = process_inbound(
            raw_body=raw,
            signature=signature,
            secret=webhook_secret,
            fields=parse_textline_fields(payload),
            driver=driver,
            rate_limiter=rate_limiter,
            resolved_at=clock(),
            is_duplicate=is_duplicate,
            event_time=event_time,
            event_type=event_type,
        )

        # Opt-out is the only reply the gateway sends itself (compliance
        # short-circuit, no agent turn). All other replies come from the turn.
        if (
            decision.action == "opt_out"
            and reply_sender is not None
            and decision.event is not None
            and decision.reply is not None
        ):
            reply_sender(decision.event.conversation_id, decision.reply)

        # Accepted turn: persist before acking (memory is the source of truth) and
        # enqueue the minimal async job (ADR-0105/0107). Only enqueue decisions get
        # here; opt-out/duplicate/rate-limited/retry never start a turn.
        if decision.action == "enqueue":
            context, created = store.persist_accepted_inbound(decision)
            if created:
                queue.enqueue(to_job_payload(context))

        return Response(status_code=decision.status)

    @app.post("/internal/jobs/agent-turn")
    async def agent_turn(request: Request) -> Response:
        # Local-dev shared-secret auth (ADR-0106), constant-time and fail-closed.
        # Production verifies Cloud Tasks OIDC upstream; this route is never a
        # public ingress surface.
        supplied = request.headers.get(INTERNAL_JOB_SECRET_HEADER)
        if (
            not internal_job_secret
            or not supplied
            or not hmac.compare_digest(supplied, internal_job_secret)
        ):
            return Response(status_code=401)

        raw = await request.body()
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        payload = AgentJobPayload(
            event_id=str(body.get("event_id", "")),
            conversation_id=str(body.get("conversation_id", "")),
        )

        # Memory is the source of truth (ADR-0107): reload by eventId, verify the
        # conversation binding, and run the shared guarded turn — the same logic the
        # local dispatcher uses, so HTTP and in-process delivery cannot drift.
        outcome = execute_agent_turn_job(
            store=store, turn_runner=turn_runner, payload=payload
        )
        if outcome is AgentJobOutcome.CONTEXT_NOT_FOUND:
            return Response(status_code=404)
        if outcome is AgentJobOutcome.BINDING_MISMATCH:
            return Response(status_code=409)
        return Response(status_code=200)

    return app
