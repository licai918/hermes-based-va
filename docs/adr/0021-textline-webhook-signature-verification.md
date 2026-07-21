# Required Textline webhook signature verification

> **Superseded in part (2026-07-21).** The signature *mechanism* is gone —
> SimpleTexting does not sign webhooks, so inbound auth is a token in the registered
> URL and the IP-allowlist waiver below no longer rests on anything. The *requirement*
> stands and is still the live citation in `gateway/verify.py`: authenticate inbound
> webhooks before processing, 401 on failure, credentials server-side only.
> Superseding decision → [ADR-0153](0153-provider-neutral-sms-tool-naming.md).

The first-version Textline integration must verify inbound webhook authenticity before Hermes processes an SMS event. Requests that fail signature or token validation return 401 and do not enter the **External Customer Service Profile** flow.

Textline API credentials remain server-side environment variables only. Webhook logs may record source metadata and conversation identifiers but must not store secrets or full credential values.

IP allowlists are not required for MVP when signature verification is enforced.

**Considered options:** accept unsigned webhooks in dev only (rejected for production path); defer verification to phase 2 (rejected—exposes a public ingress risk).
