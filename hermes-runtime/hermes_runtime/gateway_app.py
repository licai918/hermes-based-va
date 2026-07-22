"""SMS/email gateway HTTP surface (ADR-0095 Python-native, ADR-0103/0104/0108).

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
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from fastapi import FastAPI, Request, Response

from toee_hermes.drivers.mock import MockDriver, create_all_mock_handlers
from toee_hermes.execute import ToolDriver
from toee_hermes.gateway.agent_turn import AgentJobPayload, AgentTurnContext
from toee_hermes.gateway.normalize import (
    InboundChannelEvent,
    SmsInboundFields,
    normalize_e164,
    to_inbound_email_event,
)
from toee_hermes.gateway.pipeline import DuplicateCheck, process_inbound
from toee_hermes.gateway.verify import verify_webhook_token
from toee_hermes.gateway.rate_limit import (
    InboundRateLimiter,
    create_inbound_rate_limiter,
)

from hermes_runtime.agent_turn_job import AgentJobOutcome, execute_agent_turn_job
from hermes_runtime.gateway_store import GatewayStore, InMemoryGatewayStore
from hermes_runtime.outbound_send import (
    OPT_OUT_SLOT,
    InMemoryOutboundSendLog,
    OutboundSendBurned,
    deliver_once,
)

logger = logging.getLogger(__name__)

# SimpleTexting does not sign webhook payloads (ADR-0153): authenticity is a
# shared secret token in the registered webhook URL, read from this query param.
# The simulated-email route (S17) uses the same token — it is internal ingress.
WEBHOOK_TOKEN_QUERY_PARAM = "token"

# Local-dev shared-secret header for the internal agent-turn route (ADR-0106).
# Production verifies Cloud Tasks OIDC upstream instead.
INTERNAL_JOB_SECRET_HEADER = "X-Internal-Job-Secret"

# Sends a gateway-level (non-agent) reply to a conversation thread — used for the
# fixed opt-out confirmation, which must bypass the agent turn (ADR-0108/0016).
# The deployment wiring injects a real SimpleTexting client; tests inject a fake.
ReplySender = Callable[[str, str], None]

# Runs one async agent turn for a reloaded context against its inbound body. The
# production runner boots the External profile agent with the loaded session
# context and replies via governed toee_sms_reply (ADR-0107); tests inject a
# fake. run_live_turn is the eval harness, not this production seam.
# The third argument is the durable queue's job id (0.0.4 S03): half the outbound
# idempotency key, so it is framework context, never payload or model output
# (ADR-0148). None on this app's ADR-0106 parity route, which has no job row.
TurnRunner = Callable[[AgentTurnContext, str, Optional[str]], None]

# resolved_at clock for the Session Identity Snapshot (injectable for determinism).
Clock = Callable[[], str]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_ignored_simpletexting_webhook(payload: dict[str, Any]) -> bool:
    """Non-inbound SimpleTexting reports ack 200 without agent work (ADR-0102).

    One webhook registration can carry several triggers (OUTGOING_MESSAGE,
    DELIVERY_REPORT, UNSUBSCRIBE_REPORT, ...); only INCOMING_MESSAGE starts a turn.
    """
    return payload.get("type") != "INCOMING_MESSAGE"


def parse_simpletexting_fields(payload: dict[str, Any]) -> SmsInboundFields:
    """Map a SimpleTexting webhook report onto canonical inbound fields (ADR-0102).

    Shape (SimpleTexting API v2 ``SingleReportDtoWebhookMessageDto``)::

        {"reportId": "...", "webhookId": "...", "type": "INCOMING_MESSAGE",
         "values": {"messageId": "...", "text": "...", "accountPhone": "...",
                    "contactPhone": "...", "timestamp": "...", "mediaItems": [...]}}

    SimpleTexting has no conversation resource: the canonical conversation_id is
    the contact's E.164 phone, which is also what the outbound ReplySender sends
    to. Dedup keys on ``messageId`` (stable across webhook redeliveries).
    """
    values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
    contact_phone = str(values.get("contactPhone", ""))
    media = values.get("mediaItems")
    media_urls: Optional[list[str]] = None
    if isinstance(media, list):
        # ponytail: MMS mediaItems arrive as SimpleTexting media IDs, not URLs;
        # fetch via GET /api/mediaitems/{id} if inbound media handling ever lands.
        media_urls = [str(item) for item in media if item] or None
    return SmsInboundFields(
        event_id=str(values.get("messageId") or payload.get("reportId") or ""),
        conversation_id=normalize_e164(contact_phone) if contact_phone else "",
        from_phone=contact_phone,
        body=str(values.get("text", "")),
        received_at=str(values.get("timestamp", "")),
        raw_event_type=str(payload.get("type", "")),
        media_urls=media_urls,
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
    outbound_log: Optional[Any] = None,
) -> FastAPI:
    """Build the SMS/email gateway app from its injected collaborators.

    Defaults are mock-first (ADR-0137) and in-memory (ADR-0140 dev substrate): an
    unconfigured app boots against the mock driver, a fresh in-process rate limiter,
    and an in-memory store. The deployment composition root injects the resolved
    integration driver, the durable idempotency check, the real SimpleTexting reply
    client, the Postgres-backed store, and the durable ``outbound_log`` that fences
    the opt-out confirmation against a webhook redelivery (FR-12).

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
    # FR-12: the opt-out confirmation is an outbound send too, so it needs the same
    # record. Defaults in-memory for the DB-free callers, same reasoning as
    # make_gateway_turn_runner -- never an unguarded branch.
    outbound_log = outbound_log if outbound_log is not None else InMemoryOutboundSendLog()

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
        #
        # The confirmation goes through the SAME deliver_once wrap as the agent
        # reply (FR-12, fix wave 1 finding 2). It is not covered by the
        # `idempotency` stage upstream: that stage's `is_duplicate` reads
        # `agent_turn_context`, and the opt_out branch returns before
        # persist_accepted_inbound ever writes such a row -- so a redelivered STOP
        # is NOT seen as a duplicate and used to text a second confirmation. There
        # is no job here, so the key is derived from the event identity alone
        # (`no-job:{event_id}:opt-out`), which is the same fencing the ADR-0106
        # parity route already relies on: enforcement is on `event_id`.
        #
        # `claim_event` (main, ADR-0153) stays in front of it and is not redundant:
        # SimpleTexting does not sign webhooks, so a captured request replays
        # verbatim, and this branch persists no context for is_duplicate to catch.
        # It is the compare-and-set that stops the replay before it reaches the
        # sender; deliver_once is the durable record that the send itself is
        # at-most-once. Both, because they fail closed on different failures.
        if (
            decision.action == "opt_out"
            and reply_sender is not None
            and decision.event is not None
            and decision.reply is not None
            and store.claim_event(decision.event.event_id)
        ):
            event, confirmation = decision.event, decision.reply
            try:
                deliver_once(
                    log=outbound_log,
                    job_id=None,
                    event_id=event.event_id,
                    conversation_id=event.conversation_id,
                    channel=event.channel,
                    slot=OPT_OUT_SLOT,
                    deliver=lambda: reply_sender(event.conversation_id, confirmation),
                )
            except OutboundSendBurned:
                # Fix wave 2 finding 1: a burned key is non-retryable by
                # definition. process_inbound short-circuits at the opt_out
                # stage on every redelivery of this STOP -- the customer IS
                # opted out and no turn is ever enqueued -- so 500ing forever
                # only risks the provider backing off or disabling this
                # endpoint for every OTHER customer's inbound webhook (ADR-0103
                # rejects non-200 for a post-decision outbound failure;
                # ADR-0104 assigns opt-out 200). The failed row is the durable
                # record an operator reads (S05's dead-letter/audit view).
                logger.error(
                    "Customer %s (event %s) is opted out but never received "
                    "the ADR-0016 confirmation text -- the send failed and "
                    "the outbound_send key is now permanently spent",
                    event.conversation_id,
                    event.event_id,
                )
        if decision.action == "enqueue":
            store.persist_accepted_inbound(decision)
        return Response(status_code=decision.status)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        # Cheap liveness probe for the Cloud Run health check (ADR-0098, issue #33):
        # no secret, store, or turn-runner dependency, so it answers before (and
        # independently of) any inbound traffic. Readiness of the model/SimpleTexting
        # connections is enforced at boot by build_gateway_app (fail-closed).
        return {"status": "ok"}

    @app.post("/webhooks/simpletexting")
    async def simpletexting_webhook(request: Request) -> Response:
        raw = await request.body()
        token = request.query_params.get(WEBHOOK_TOKEN_QUERY_PARAM)
        # A non-UTF-8 body is unparseable, not a crash: this runs before the auth
        # gate, so letting UnicodeDecodeError escape let any unauthenticated caller
        # force a 500 plus a traceback. Treat undecodable input as an empty payload
        # and let the token check below decide the response.
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        # Authenticate before any branch acts on the payload — a request without the
        # registered URL token must never earn a 200, even the ignored-report
        # short-circuit (process_inbound re-verifies; fail-closed, ADR-0021).
        if not verify_webhook_token(token=token, secret=webhook_secret):
            return Response(status_code=401)

        if is_ignored_simpletexting_webhook(payload):
            return Response(status_code=200)

        fields = parse_simpletexting_fields(payload)
        if not fields.event_id:
            # Fix wave 2 finding 2: every outbound_send row is keyed on
            # event_id alone (migration 0012, UNIQUE(event_id)). A blank id --
            # missing `id`/`post.uuid` -- would collapse a different customer's
            # STOP confirmation or reply onto this same row. Fail closed, same
            # shape as the signature/staleness checks above.
            return Response(status_code=401)

        decision = process_inbound(
            token=token,
            secret=webhook_secret,
            fields=fields,
            driver=driver,
            rate_limiter=rate_limiter,
            resolved_at=clock(),
            is_duplicate=is_duplicate,
        )
        return _dispatch_decision(decision)

    @app.post("/webhooks/simulated-email")
    async def simulated_email_webhook(request: Request) -> Response:
        # Simulated email ingress (S17/FR-18, RK-4: no real provider). Same fast-ack
        # shape as the SMS webhook: authenticate on the shared URL token, run the
        # SAME process_inbound (Email Sender Match + governed turn + reply mirror),
        # map the status. This is internal ingress driven by the Workbench simulator,
        # so it shares the gateway's one auth mechanism (ADR-0153).
        raw = await request.body()
        token = request.query_params.get(WEBHOOK_TOKEN_QUERY_PARAM)
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        if not verify_webhook_token(token=token, secret=webhook_secret):
            return Response(status_code=401)

        event = parse_simulated_email_event(payload)
        if not event.event_id:
            # Fix wave 2 finding 2 (same guard as the SMS route above).
            return Response(status_code=401)

        decision = process_inbound(
            token=token,
            secret=webhook_secret,
            event=event,
            driver=driver,
            rate_limiter=rate_limiter,
            resolved_at=clock(),
            is_duplicate=is_duplicate,
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
