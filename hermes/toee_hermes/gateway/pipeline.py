"""Inbound Textline pipeline orchestrator (ADR-0104, ADR-0108, ADR-0109, ADR-0043).

Composes the stable gateway primitives into a single, deterministic decision the
route/embedding layer acts on. This is the "Hermes embedding" seam: it resolves
the Session Identity Snapshot and says whether to ack, short-circuit, throttle,
retry, or enqueue the async agent turn — but performs no I/O itself (signature
secret, identity driver, idempotency check, and rate limiter are injected; the
route layer persists state and enqueues the job per the returned decision).

Stage order follows ADR-0103 (verify -> normalize -> dedup -> ingress -> persist)
with the ADR-0108 opt-out and ADR-0109 rate-limit overlays, and HTTP outcomes
follow ADR-0104:

    verify(401) -> normalize -> idempotency(200) -> opt-out(200, short-circuit) ->
    ingress(500 transient | 200 normal) -> rate-limit(200, snapshot, no enqueue) ->
    accept(200, enqueue)

Opt-out short-circuits before ingress (the fixed confirmation needs no identity).
Rate-limit runs after ingress because ADR-0109 only skips the async enqueue — the
turn is still ingress-resolved and persisted, so a throttled turn keeps its
Session Identity Snapshot for audit and Copilot context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Union

from toee_hermes.errors import ToolErrorClass
from toee_hermes.execute import ToolDriver
from toee_hermes.gateway.ingress import (
    SessionIdentitySnapshot,
    match_ingress_email,
    match_ingress_phone,
)
from toee_hermes.gateway.normalize import (
    InboundChannelEvent,
    TextlineInboundFields,
    is_email_channel,
    to_inbound_channel_event,
)
from toee_hermes.gateway.opt_out import SMS_OPT_OUT_CONFIRMATION, is_opt_out_keyword
from toee_hermes.gateway.rate_limit import InboundRateLimiter
from toee_hermes.gateway.verify import verify_textline_signature

# eventId -> already processed? (route layer consults the datastore). Default
# never-duplicate keeps the orchestrator pure for callers without idempotency yet.
DuplicateCheck = Callable[[str], bool]


@dataclass(frozen=True)
class InboundDecision:
    """The route layer reads this to persist, ack, reply, retry, or enqueue."""

    status: int  # 401 | 200 | 500
    action: str  # reject | duplicate | opt_out | rate_limited | retry | enqueue
    stage: str  # verify | idempotency | opt_out | rate_limit | ingress | accept
    retryable: bool = False
    error_class: Optional[ToolErrorClass] = None
    event: Optional[InboundChannelEvent] = None
    snapshot: Optional[SessionIdentitySnapshot] = None
    reply: Optional[str] = None  # fixed opt-out confirmation, when action == opt_out

    @property
    def enqueue(self) -> bool:
        """Whether the route layer should enqueue the async agent turn."""
        return self.action == "enqueue"


def process_inbound(
    *,
    raw_body: Union[str, bytes],
    signature: Optional[str],
    secret: str,
    fields: Optional[TextlineInboundFields] = None,
    event: Optional[InboundChannelEvent] = None,
    driver: ToolDriver,
    rate_limiter: InboundRateLimiter,
    resolved_at: str,
    is_duplicate: DuplicateCheck = lambda event_id: False,
    at_ms: Optional[float] = None,
    event_time: Optional[str] = None,
    event_type: Optional[str] = None,
) -> InboundDecision:
    """Decide an inbound turn for SMS (``fields``) or email (``event``, S17/FR-18).

    SMS callers pass ``fields`` (normalized here via ``to_inbound_channel_event``);
    the simulated-email route passes an already-built ``event`` (subject folded into
    the body upstream). The channel-agnostic core — verify, dedup, rate-limit,
    accept — is shared; only identity match and the SMS-only opt-out short-circuit
    branch on the channel.
    """
    # Verify: reject unsigned/forged traffic before any processing (ADR-0021).
    if not verify_textline_signature(
        raw_body=raw_body,
        signature=signature,
        secret=secret,
        event_time=event_time,
        event_type=event_type,
    ):
        return InboundDecision(status=401, action="reject", stage="verify")

    if event is None:
        if fields is None:
            raise ValueError("process_inbound requires exactly one of fields/event.")
        event = to_inbound_channel_event(fields)
    is_email = is_email_channel(event.channel)

    # Idempotency: a redelivered eventId is a no-op ack — ordered before opt-out
    # so a STOP the caller *already knows about* cannot trigger a second
    # confirmation (ADR-0016).
    #
    # This stage is NOT what makes the opt-out confirmation safe. The durable
    # `is_duplicate` (PostgresGatewayStore) reads `agent_turn_context`, and the
    # opt_out branch below returns before anything persists such a row — so a
    # redelivered STOP arrives here looking brand new every time. The guard that
    # actually holds is the outbound record on the send itself (FR-12,
    # gateway_app._dispatch_decision -> deliver_once).
    if is_duplicate(event.event_id):
        return InboundDecision(
            status=200, action="duplicate", stage="idempotency", event=event
        )

    # Opt-out: SMS-only compliance short-circuit (ADR-0108/0015/0016). Email is not
    # STOP-gated the same way (S17/RK-4) — its "STOP" is prose, not a keyword.
    if not is_email and is_opt_out_keyword(event.body):
        return InboundDecision(
            status=200,
            action="opt_out",
            stage="opt_out",
            event=event,
            reply=SMS_OPT_OUT_CONFIRMATION,
        )

    # Ingress identity match: resolve the Session Identity Snapshot synchronously
    # before persist (ADR-0103 step 4, ADR-0043). Phone for SMS, From address for
    # email (ADR-0052/0054). Transient lookup failure is a retryable 500 (ADR-0104);
    # no-match and ambiguous are normal 200 states.
    if is_email:
        ingress = match_ingress_email(
            from_address=event.from_phone, driver=driver, resolved_at=resolved_at
        )
    else:
        ingress = match_ingress_phone(
            phone=event.from_phone, driver=driver, resolved_at=resolved_at
        )
    if ingress.retryable_error:
        return InboundDecision(
            status=500,
            action="retry",
            stage="ingress",
            retryable=True,
            error_class=ingress.error_class,
            event=event,
        )

    # Rate limit: over-limit senders are still ingress-resolved and persisted and
    # acked, but skip only the async job enqueue (ADR-0109).
    if not rate_limiter.check(event.from_phone, at_ms).allowed:
        return InboundDecision(
            status=200,
            action="rate_limited",
            stage="rate_limit",
            event=event,
            snapshot=ingress.snapshot,
        )

    return InboundDecision(
        status=200,
        action="enqueue",
        stage="accept",
        event=event,
        snapshot=ingress.snapshot,
    )
