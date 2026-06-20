# Composio Connected Account onboarding batch summary

This ADR closes the Composio Connected Account onboarding grill. It summarizes ADR-0133 through ADR-0137 and records the end-to-end ops model for Text-First Launch.

## Decision summary

| Topic | v1 decision |
|-------|-------------|
| Where onboarding happens | Ops-side Composio Dashboard or CLI; no v1 workbench UI |
| Admin routes | Unchanged three-route **Admin Governance Console** |
| Composio identity | `user_id` per environment plus per-toolkit `connected_account_id` |
| Auth configs | Composio-managed for Shopify, QBO, and Square |
| Environment isolation | Separate accounts for `toee-staging` and `toee-production` |
| Failure handling | Lazy runtime failure, governed Tool Unavailable, ops alert, manual reconnect |
| Local development | `INTEGRATION_DRIVER=mock` default; optional `toee-local-<developer>` live link |
| Secrets | Only `COMPOSIO_API_KEY` in Secret Manager; connected account ids are non-secret env config |

## Supporting ADRs

| ADR | Topic |
|-----|-------|
| 0129 | Credential hosting model (updated for v3 naming) |
| 0133 | Ops-side onboarding without workbench UI |
| 0134 | Composio-managed auth configs |
| 0135 | Environment-isolated connected accounts |
| 0136 | Lazy failure handling and ops alerting |
| 0137 | Local mock-default with optional composio driver |

## End-to-end onboarding flow

```text
1. Ops creates Composio-managed auth configs (Shopify, QBO, Square)
2. Ops runs connected_accounts.link() per environment user_id
3. Ops stores connected_account_id values in Cloud Run env
4. Ops injects COMPOSIO_API_KEY from Secret Manager
5. Deploy composio driver for Layer 1 adapters
6. Run staging smoke on toee_* actions
7. Repeat link + env update for production before go-live
```

## Runtime configuration example

```text
# Secret Manager
COMPOSIO_API_KEY

# Cloud Run env (non-secret)
COMPOSIO_USER_ID=toee-production
COMPOSIO_SHOPIFY_CONNECTED_ACCOUNT_ID=ca_...
COMPOSIO_QBO_CONNECTED_ACCOUNT_ID=ca_...
COMPOSIO_SQUARE_CONNECTED_ACCOUNT_ID=ca_...
INTEGRATION_DRIVER=composio
```

Staging uses the same variable names with `toee-staging` and staging connected account ids.

## Reconnect runbook trigger

When ADR-0136 logs show `error_class=auth_expired` or `configuration_missing`, ops repeats link for the affected toolkit and environment, updates env if the connected account id changed, and reruns Layer 1 smoke.

Step-by-step commands: [docs/ops/composio-connected-accounts.md](../ops/composio-connected-accounts.md).

## What v1 explicitly does not build

- `/admin/integrations` workbench route
- customer-facing OAuth or Composio connect prompts
- Cloud Run readiness gates on Composio auth health
- shared production connected accounts in staging or local dev

## Relationship to ADR-0132

ADR-0132 records mock-first adapter delivery. This ADR records the ops steps required before enabling `INTEGRATION_DRIVER=composio` in staging and production.

**Considered options:** defer all onboarding decisions until after Runner implementation (rejected—environment and ops boundaries affect adapter config now); add workbench OAuth UI in the same phase (rejected—unnecessary for one-time internal setup); single shared connected account across environments (rejected in ADR-0135).
