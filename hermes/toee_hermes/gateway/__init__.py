"""Textline inbound gateway primitives (ADR-0102, ADR-0021, ADR-0108, ADR-0109).

Schema-independent core for the Textline pipeline, ported from the TypeScript
hermes-gateway: signature verification, canonical normalization, opt-out keyword
detection, and the per-phone soft rate limiter. The route/embedding layer wires
these into the live webhook handler and Hermes agent turn.
"""

from __future__ import annotations

from toee_hermes.gateway.agent_turn import (
    AgentJobPayload,
    AgentTurnContext,
    build_agent_turn_context,
    job_payload_matches,
    to_job_payload,
)
from toee_hermes.gateway.ingress import (
    IngressMatchResult,
    SessionIdentitySnapshot,
    match_ingress_email,
    match_ingress_phone,
)
from toee_hermes.gateway.normalize import (
    InboundChannelEvent,
    TextlineInboundFields,
    canonicalize_email,
    is_email_channel,
    normalize_e164,
    to_inbound_channel_event,
    to_inbound_email_event,
)
from toee_hermes.gateway.opt_out import SMS_OPT_OUT_CONFIRMATION, is_opt_out_keyword
from toee_hermes.gateway.pipeline import InboundDecision, process_inbound
from toee_hermes.gateway.rate_limit import (
    InboundRateLimiter,
    RateLimitDecision,
    create_inbound_rate_limiter,
)
from toee_hermes.gateway.verify import verify_textline_signature

__all__ = [
    "InboundChannelEvent",
    "TextlineInboundFields",
    "normalize_e164",
    "canonicalize_email",
    "is_email_channel",
    "to_inbound_channel_event",
    "to_inbound_email_event",
    "SMS_OPT_OUT_CONFIRMATION",
    "is_opt_out_keyword",
    "InboundRateLimiter",
    "RateLimitDecision",
    "create_inbound_rate_limiter",
    "verify_textline_signature",
    "IngressMatchResult",
    "SessionIdentitySnapshot",
    "match_ingress_phone",
    "match_ingress_email",
    "InboundDecision",
    "process_inbound",
    "AgentJobPayload",
    "AgentTurnContext",
    "build_agent_turn_context",
    "job_payload_matches",
    "to_job_payload",
]
