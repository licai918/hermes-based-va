# Lazy Composio connection failure handling with ops alerting

v1 does not add startup probes, scheduled health jobs, or workbench connection-status UI for Composio Connected Accounts. Connection health is detected when a Layer 1 composio driver call fails at runtime.

## Runtime behavior

When a Composio-backed `toee_*` action fails because of auth expiry, revoked access, vendor timeout, or Composio API errors:

1. the adapter returns a governed **Tool Unavailable Response** to Hermes
2. the external profile follows existing playbooks such as safe fallback language and **Follow-up Case** creation where the scenario requires it
3. the adapter writes audit metadata with tool name, v1 `action`, `user_id`, `connected_account_id`, and `error_class`
4. structured server logs emit the same fields for operations alerting

Customer-facing replies must not expose Composio errors, OAuth state, or raw vendor credentials.

## Error classes

v1 adapter logging uses a small `error_class` enum such as:

| `error_class` | Typical cause |
|---------------|---------------|
| `auth_expired` | Connected account credentials no longer valid |
| `vendor_timeout` | Shopify, QBO, or Square upstream timeout |
| `composio_api_error` | Composio platform failure unrelated to customer input |
| `configuration_missing` | Missing `COMPOSIO_API_KEY`, `user_id`, or `connected_account_id` in the active environment |

## Operations response

Reconnect procedures follow ADR-0133:

1. identify the affected environment and toolkit from logs
2. rerun `connected_accounts.link()` for that toolkit
3. update the environment `connected_account_id` if Composio returns a new id
4. rerun staging or production Layer 1 smoke for the affected `toee_*` actions

## Alerting

Cloud Logging alerts or equivalent operations monitors watch for `error_class` values `auth_expired` and `configuration_missing` on Layer 1 adapter logs. v1 does not block Cloud Run readiness on Composio availability.

A future scheduled health job or admin status page may be added by ADR if operational volume requires it.

**Considered options:** fail Cloud Run readiness when Composio auth is invalid (rejected—Textline ingress should not depend on Shopify OAuth state); daily scheduled Composio health polling in v1 (rejected—extra infrastructure before go-live need); workbench connection dashboard in v1 (rejected—ADR-0133 keeps onboarding ops-side).
