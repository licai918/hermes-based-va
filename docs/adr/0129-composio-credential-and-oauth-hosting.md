# Composio credential and OAuth hosting for Layer 1 adapters

> **Amended by [ADR-0139](0139-hermes-is-nous-python-agent-plugin-integration.md).**
> Layer 1 Composio adapters run in the Python `toee_hermes` plugin's Composio
> driver (ADR-0127, ADR-0132), reached through the Python gateway embedding — not a
> TypeScript `packages/hermes-runtime` invoked from `apps/workbench` or
> `services/hermes-gateway`. The credential model below (per-service key injection,
> no global process-wide secret file) is unchanged.

Layer 1 **Domain Adapter Tools** from ADR-0128 may use Composio internally. Tooe Tire uses a hybrid credential model that keeps server secrets in GCP while delegating SaaS OAuth refresh to Composio Connected Accounts.

Connected Account onboarding is performed ops-side without Workbench UI per ADR-0133.

## Secret storage

Production stores the Composio platform API key as a server secret:

| Variable | Location | Scope |
|----------|----------|-------|
| `COMPOSIO_API_KEY` | GCP Secret Manager → Cloud Run env on services that run Layer 1 adapters | Server-side only |

Local development supplies the same key through service `.env.local` files per ADR-0098. The key must not appear in workbench browser code, client bundles, eval fixtures, or webhook logs.

## Connected Accounts

Shopify, QuickBooks, and Square OAuth for the single Toee Tire merchant per environment are established through Composio Connected Accounts during ops-side onboarding per ADR-0133.

Runtime configuration stores:

| Variable | Secret? | Purpose |
|----------|---------|---------|
| `COMPOSIO_USER_ID` | No | Fixed Composio `user_id` for the deployment environment, such as `toee-production` |
| `COMPOSIO_SHOPIFY_CONNECTED_ACCOUNT_ID` | No | Active Shopify connected account for that `user_id` |
| `COMPOSIO_QBO_CONNECTED_ACCOUNT_ID` | No | Active QuickBooks connected account |
| `COMPOSIO_SQUARE_CONNECTED_ACCOUNT_ID` | No | Active Square connected account |

Adapters pass `user_id` and the toolkit `connected_account_id` to Composio SDK calls. Adapters do not read, log, or persist raw vendor access tokens or refresh tokens in **Hermes Native Memory**.

`connected_account_id` values are operational references, not bearer credentials. They may live in plain Cloud Run environment configuration. Only `COMPOSIO_API_KEY` must stay in Secret Manager in v1.

## Service placement

Both `apps/workbench` and `services/hermes-gateway` may invoke Layer 1 adapters through `packages/hermes-runtime`, but only the service that actually executes the adapter needs the Composio API key injected. Shared adapter code must not assume a global process-wide secret file.

Textline, EasyRoutes, workbench session, and internal job secrets remain outside the Composio credential model.

## Onboarding and operations

- OAuth connect flows run through Composio Dashboard or CLI during initial setup, not through customer-facing Hermes channels or v1 workbench UI.
- Connected Accounts are single-merchant per environment in v1. Multi-tenant Connected Account routing is out of scope.
- Token refresh and vendor OAuth rotation are Composio responsibilities behind the connected account reference.
- If Composio is removed later, Layer 1 adapters may swap to GCP Secret Manager-stored vendor tokens without changing `toee_*` tool contracts.

## Audit and eval boundaries

Adapter audit records include tool name, v1 `action`, `user_id`, connected account reference, and pass/fail outcome. They exclude Composio API keys and vendor tokens.

**Launch Eval** continues to mock `toee_*` actions. The runner does not require live Composio credentials.

**Considered options:** store all vendor refresh tokens directly in GCP Secret Manager and skip Composio Connected Accounts (rejected for v1—more rotation work without changing the external tool contract); store Connected Account secrets in workbench admin UI (rejected—widens secret exposure); require Composio credentials for eval runs (rejected—blocks CI and local fixture-first workflow).
