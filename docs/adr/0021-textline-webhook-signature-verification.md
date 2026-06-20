# Required Textline webhook signature verification

The first-version Textline integration must verify inbound webhook authenticity before Hermes processes an SMS event. Requests that fail signature or token validation return 401 and do not enter the **External Customer Service Profile** flow.

Textline API credentials remain server-side environment variables only. Webhook logs may record source metadata and conversation identifiers but must not store secrets or full credential values.

IP allowlists are not required for MVP when signature verification is enforced.

**Considered options:** accept unsigned webhooks in dev only (rejected for production path); defer verification to phase 2 (rejected—exposes a public ingress risk).
