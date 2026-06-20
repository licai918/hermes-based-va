# Environment-isolated Composio Connected Accounts

Staging and production deployments use separate Composio `user_id` values and separate per-toolkit `connected_account_id` values. Production Connected Accounts are not reused in staging, local development, or CI.

## Environment mapping

| Deployment | `COMPOSIO_USER_ID` | Connected accounts |
|------------|-------------------|-------------------|
| Production Cloud Run | `toee-production` | independent Shopify, QBO, and Square `connected_account_id` values |
| Staging Cloud Run | `toee-staging` | independent Shopify, QBO, and Square `connected_account_id` values |
| Local developer optional link | `toee-local-<developer>` | optional; must never reuse production ids |

Each environment stores its own:

- `COMPOSIO_USER_ID`
- `COMPOSIO_SHOPIFY_CONNECTED_ACCOUNT_ID`
- `COMPOSIO_QBO_CONNECTED_ACCOUNT_ID`
- `COMPOSIO_SQUARE_CONNECTED_ACCOUNT_ID`

## Onboarding per environment

Ops-side link procedures from ADR-0133 run separately for staging and production. Completing production onboarding does not satisfy staging smoke requirements.

Early staging may keep Layer 1 adapters on mock drivers per ADR-0132. Before Text-First go-live, staging must complete its own Composio links and pass governed `toee_*` smoke in that environment.

## Vendor tenant note

Composio account isolation does not by itself create vendor sandboxes. If Shopify, QuickBooks, or Square provide separate sandbox tenants, the ops runbook should record which tenant each environment uses.

If only one live vendor tenant exists, staging may still use isolated Composio connected accounts while pointing at the same vendor tenant. In that case staging smoke must restrict itself to read-only Layer 1 actions and avoid payment-link or other side-effectful tests unless a dedicated sandbox tenant exists.

## CI and eval

**Launch Eval** and CI continue to use mock drivers and do not require Composio credentials. CI must not load production or staging `connected_account_id` values.

**Considered options:** share production connected accounts with staging (rejected—staging smoke can hit live merchant data); isolate only local dev (rejected—staging would still share production credentials); skip staging links entirely (rejected—no realistic pre-production integration gate).
