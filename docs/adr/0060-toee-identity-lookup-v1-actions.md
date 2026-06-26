# toee_identity_lookup v1 actions for ingress and email-link checks

`toee_identity_lookup` exposes three v1 **Domain Adapter Tool Action** values:

| Action | Primary caller | Purpose |
|--------|----------------|---------|
| `match_phone` | **Channel Gateway** on Textline SMS and voice ingress | Resolve **Ingress Phone Match** and write **Session Identity Snapshot** |
| `match_email_sender` | **Channel Gateway** on email ingress | Resolve **Email Sender Match** on authenticated **From** and write session identity |
| `get_email_link_status` | **Hermes Core** agent turns before accounting reads | Return **Customer Email Link** readiness between matched **Shopify Customer** and **QBO Customer** |

`match_phone` and `match_email_sender` complete before the external agent turn begins. The agent receives identity state from session context rather than calling those actions directly in normal customer flows.

`get_email_link_status` may also be invoked internally by `toee_qbo_read` **Tool Gate**, but remains a separate action for eval and audit clarity.

**Considered options:** one `resolve_identity` action with channel parameter (rejected—weaker ingress clarity); add `get_session_snapshot` for agent self-read (rejected—identity should come from session context, not ad hoc agent lookup); fold email-link checks only into `toee_qbo_read` with no standalone action (rejected—harder to test email-link failure independently).
