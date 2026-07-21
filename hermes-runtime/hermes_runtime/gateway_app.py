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
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from fastapi import FastAPI, Request, Response

from toee_hermes.drivers.mock import MockDriver, create_all_mock_handlers
from toee_hermes.execute import ToolDriver
from toee_hermes.gateway.agent_turn import AgentJobPayload, AgentTurnContext
from toee_hermes.gateway.normalize import (
    InboundChannelEvent,
    TextlineInboundFields,
    to_inbound_email_event,
)
from toee_hermes.gateway.pipeline import DuplicateCheck, process_inbound
from toee_hermes.gateway.verify import verify_textline_signature
from toee_hermes.gateway.rate_limit import (
    InboundRateLimiter,
    create_inbound_rate_limiter,
)

from hermes_runtime.agent_turn_job import AgentJobOutcome, execute_agent_turn_job
from hermes_runtime.gateway_store import GatewayStore, InMemoryGatewayStore

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
# The third argument is the durable queue's job id (0.0.4 S03): half the outbound
# idempotency key, so it is framework context, never payload or model output
# (ADR-0148). None on this app's ADR-0106 parity route, which has no job row.
TurnRunner = Callable[[AgentTurnContext, str, Optional[str]], None]

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


def parse_simulated_email_event(payload: dict[str, Any]) -> InboundChannelEvent:
    """Map a simulated inbound email JSON body onto the canonical event (S17/FR-18).

    Shape: ``{from, subject, body, conversation_id?, id?, received_at?}``. ADR-0054:
    only the authenticated envelope ``from`` is used for identity — never a body- or
    header-supplied Reply-To. Subject is folded into the turn body by
    ``to_inbound_email_event`` so the governed turn sees it.
    """
    conversation_id = str(payload.get("conversation_id") or payload.get("id") or "")
    return to_inbound_email_event(
        event_id=str(payload.get("id", "")),
        conversation_id=conversation_id,
        from_address=str(payload.get("from", "")),
        subject=str(payload.get("subject", "")),
        body=str(payload.get("body", "")),
        received_at=str(payload.get("received_at", "")),
        raw_event_type=str(payload.get("type", "email.received")),
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


# Opt-in replay window (seconds). The TGP signature covers only type+time+secret,
# not the body, and never expires — so a leaked (signature, time, type) triple can
# be replayed. Set TEXTLINE_MAX_SIGNATURE_AGE_SECONDS to reject stale events.
_MAX_SIGNATURE_AGE_ENV = "TEXTLINE_MAX_SIGNATURE_AGE_SECONDS"


def _now_unix() -> float:
    return time.time()


def _max_signature_age_seconds() -> Optional[int]:
    raw = (os.environ.get(_MAX_SIGNATURE_AGE_ENV) or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _tgp_event_is_stale(
    event_time: Optional[str], max_age_seconds: Optional[int], now_unix: float
) -> bool:
    """True when an opted-in freshness window is exceeded (replay protection)."""
    if not max_age_seconds or not event_time:
        return False
    try:
        ts = int(str(event_time).strip())
    except (TypeError, ValueError):
        return False
    return abs(now_unix - ts) > max_age_seconds


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
    internal_job_secret: Optional[str] = None,
    turn_runner: Optional[TurnRunner] = None,
) -> FastAPI:
    """Build the Textline gateway app from its injected collaborators.

    Defaults are mock-first (ADR-0137) and in-memory (ADR-0140 dev substrate): an
    unconfigured app boots against the mock driver, a fresh in-process rate limiter,
    and an in-memory store. The deployment composition root injects the resolved
    integration driver, the durable idempotency check, the real Textline reply
    client, and the Postgres-backed store.

    There is no ``queue`` seam: enqueuing the turn job is the store's job, so that
    it shares the persist transaction (see :meth:`GatewayStore.persist_accepted_inbound`).
    To observe or run the enqueued turn in a test, inject the queue into the store
    (``InMemoryGatewayStore(queue=...)``).
    """
    driver = driver or MockDriver(create_all_mock_handlers())
    rate_limiter = rate_limiter or create_inbound_rate_limiter()
    is_duplicate = is_duplicate or _never_duplicate
    clock = clock or _utc_now_iso
    store = store or InMemoryGatewayStore()

    app = FastAPI()

    def _dispatch_decision(decision) -> Response:
        # Shared tail for both ingress routes (SMS + simulated email): send the one
        # fixed opt-out confirmation when required, then hand an accepted turn to the
        # store before acking (memory is the source of truth, ADR-0105/0107). Only
        # opt-out and enqueue decisions act here; duplicate/rate-limited/retry/reject
        # just map their status.
        #
        # persist_accepted_inbound persists AND enqueues, in one transaction. The
        # route deliberately does not enqueue: an enqueue here is a second commit
        # boundary, and a crash inside it loses a message this response has already
        # acked -- with no redelivery to save it, since the persisted context makes
        # the retry a `duplicate` upstream of this function (US3, S02 fix wave 1).
        if (
            decision.action == "opt_out"
            and reply_sender is not None
            and decision.event is not None
            and decision.reply is not None
        ):
            reply_sender(decision.event.conversation_id, decision.reply)
        if decision.action == "enqueue":
            store.persist_accepted_inbound(decision)
        return Response(status_code=decision.status)

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

        # Authenticate before any branch acts on the payload — a forged/unsigned
        # request must never earn a 200, even the ignored-webhook short-circuit
        # (process_inbound re-verifies; this is the fail-closed gate, ADR-0021).
        if not verify_textline_signature(
            raw_body=raw,
            signature=signature,
            secret=webhook_secret,
            event_time=event_time,
            event_type=event_type,
        ):
            return Response(status_code=401)
        if _tgp_event_is_stale(event_time, _max_signature_age_seconds(), _now_unix()):
            return Response(status_code=401)

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
        return _dispatch_decision(decision)

    @app.post("/webhooks/simulated-email")
    async def simulated_email_webhook(request: Request) -> Response:
        # Simulated email ingress (S17/FR-18, RK-4: no real provider). Same fast-ack
        # shape as the SMS webhook — HMAC-verify the raw body, run the SAME
        # process_inbound (Email Sender Match + governed turn + reply mirror), map the
        # status. Signed with the legacy HMAC (no TGP event_time/type headers).
        raw = await request.body()
        raw_text = raw.decode("utf-8")
        signature, event_time, event_type = _webhook_signature_context(request)
        try:
            payload = json.loads(raw_text) if raw_text else {}
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        if not verify_textline_signature(
            raw_body=raw,
            signature=signature,
            secret=webhook_secret,
            event_time=event_time,
            event_type=event_type,
        ):
            return Response(status_code=401)

        decision = process_inbound(
            raw_body=raw,
            signature=signature,
            secret=webhook_secret,
            event=parse_simulated_email_event(payload),
            driver=driver,
            rate_limiter=rate_limiter,
            resolved_at=clock(),
            is_duplicate=is_duplicate,
            event_time=event_time,
            event_type=event_type,
        )
        return _dispatch_decision(decision)

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
