# Per-phone soft inbound rate limiting at Textline gateway

> **Provider retired (2026-07-21).** `services/hermes-gateway` is deleted and the provider
> is SimpleTexting; the per-phone soft limit below stands on the Python gateway.
> Superseding decision → [ADR-0153](0153-provider-neutral-sms-tool-naming.md).

`services/hermes-gateway` applies a per-sender soft rate limit to accepted inbound Textline customer messages in v1.

## v1 limit rule

The gateway tracks inbound volume by normalized `fromPhone` using a sliding window of ten accepted messages per minute.

When a sender exceeds the limit:

1. the gateway still verifies, normalizes, runs ingress matching, and persists the inbound turn when persistence succeeds
2. the gateway returns `200`
3. the gateway does not enqueue `agent-turn` or `opt-out-confirm` work
4. the gateway writes a structured `rate_limited` audit log entry

The gateway does not return `429` or other non-`2xx` responses for rate limiting in v1 because Textline webhook retries would amplify load.

## Placement in pipeline

Rate limiting is evaluated after durable persistence succeeds and before async job enqueue. Opt-out keyword handling still takes precedence for messages that are not rate-limited.

Global edge rate limiting through Cloud Armor or similar services is deferred until operational need is proven.

**Considered options:** no inbound rate limiting in v1 (rejected—single-number floods can exhaust model and business-tool quota); return `429` when limited (rejected—provider retry amplification); drop rate-limited messages without persistence (rejected—weak abuse audit trail).
