# Composio Connected Accounts Runbook

> **中文摘要**
>
> 本文说明 **Hermes VA** 如何通过 Composio v3 为 staging / production 完成 Shopify、QuickBooks、Square 的 Connected Account 授权，并将配置写入 GCP。
>
> - **受众**：Workbench Supervisor、Workbench Admin（具备 GCP 权限）或 DevOps
> - **v1 约束**：无 Workbench OAuth UI；CLI 为主、Dashboard 查 id / 排错为辅
> - **架构依据**：ADR-0129、ADR-0133–ADR-0138
> - **默认开发路径**：本地与 CI 使用 `INTEGRATION_DRIVER=mock`（ADR-0137），本文不替代 mock-first 流程

## Related ADRs

| ADR | Topic |
|-----|-------|
| [0129](../adr/0129-composio-credential-and-oauth-hosting.md) | Credential hosting |
| [0133](../adr/0133-ops-side-composio-connected-account-onboarding.md) | Ops-side onboarding |
| [0134](../adr/0134-composio-managed-auth-configs-v1.md) | Composio-managed auth configs |
| [0135](../adr/0135-environment-isolated-composio-connected-accounts.md) | Environment isolation |
| [0136](../adr/0136-lazy-composio-connection-failure-handling.md) | Failure handling |
| [0137](../adr/0137-local-dev-mock-default-optional-composio.md) | Local optional live link |
| [0138](../adr/0138-composio-connected-account-onboarding-summary.md) | Batch summary |

## Prerequisites

### Roles and access

- Composio organization access with permission to create auth configs and connected accounts
- GCP access to **Secret Manager** and **Cloud Run** for `toee-hermes-gateway` and, if it executes Layer 1 adapters, `toee-hermes-workbench`
- Vendor admin access to authorize Shopify, QuickBooks Online, and Square for the Toee Tire merchant account used in each environment

### Tools

- [Composio CLI](https://docs.composio.dev) or Node.js with `@composio/core` (or current v3 SDK package)
- `gcloud` CLI for Secret Manager and Cloud Run env updates
- Repository checkout with adapter composio drivers implemented (`INTEGRATION_DRIVER=composio`)

### Terminology (Composio v3)

| Term | Toee usage |
|------|------------|
| `user_id` | One fixed id per environment: `toee-staging`, `toee-production`, or `toee-local-<developer>` |
| `auth_config_id` | Composio-managed toolkit auth config (`ac_...`); recorded in ops notes |
| `connected_account_id` | Active linked account per toolkit (`ca_...`); stored in Cloud Run env |

Do not use legacy **entity ID** naming. See ADR-0129.

## Environment matrix

| Environment | `COMPOSIO_USER_ID` | Connected accounts | Notes |
|-------------|-------------------|-------------------|-------|
| Staging | `toee-staging` | Separate `ca_...` per toolkit | Complete onboarding before production |
| Production | `toee-production` | Separate `ca_...` per toolkit | Never reuse staging ids |
| Local optional | `toee-local-<developer>` | Per-developer ids | See [Appendix B](#appendix-b-optional-local-developer-link) |

**Rule:** Production connected accounts must not be copied into staging, CI, or another developer machine. See ADR-0135.

Record which Shopify / QBO / Square **vendor tenant** each environment uses. Composio isolation does not create vendor sandboxes by itself.

## Variable checklist

### Secret Manager (server secret)

| Variable | Description |
|----------|-------------|
| `COMPOSIO_API_KEY` | Composio platform API key |

Inject into Cloud Run services that run Layer 1 composio drivers. Do not commit to git, eval fixtures, or workbench client bundles.

### Cloud Run environment (non-secret)

| Variable | Example | Description |
|----------|---------|-------------|
| `INTEGRATION_DRIVER` | `composio` | Use `mock` in local default and CI |
| `COMPOSIO_USER_ID` | `toee-staging` | Fixed Composio user id for this deployment |
| `COMPOSIO_SHOPIFY_AUTH_CONFIG_ID` | `ac_...` | Used during link/reconnect only; optional at runtime |
| `COMPOSIO_QBO_AUTH_CONFIG_ID` | `ac_...` | Used during link/reconnect only |
| `COMPOSIO_SQUARE_AUTH_CONFIG_ID` | `ac_...` | Used during link/reconnect only |
| `COMPOSIO_SHOPIFY_CONNECTED_ACCOUNT_ID` | `ca_...` | Runtime Shopify connected account |
| `COMPOSIO_QBO_CONNECTED_ACCOUNT_ID` | `ca_...` | Runtime QBO connected account |
| `COMPOSIO_SQUARE_CONNECTED_ACCOUNT_ID` | `ca_...` | Runtime Square connected account |

Local development uses service `.env.local` files per ADR-0098. Only services that execute Layer 1 adapters need `COMPOSIO_API_KEY`.

## 1. First-time onboarding (staging)

Complete staging before production.

### 1.1 Store Composio API key

```bash
# Example: create secret and bind to gateway (adjust project/region/service)
echo -n "$COMPOSIO_API_KEY" | gcloud secrets create composio-api-key --data-file=-
gcloud run services update toee-hermes-gateway \
  --set-secrets=COMPOSIO_API_KEY=composio-api-key:latest \
  --region=REGION
```

Repeat for `toee-hermes-workbench` only if that service executes Layer 1 adapters in your deployment.

### 1.2 Verify Composio-managed auth configs

In **Composio Dashboard**:

1. Open **Auth configs** (or **Integrations**).
2. Confirm Composio-managed configs exist for **Shopify**, **QuickBooks**, and **Square**.
3. Copy each `auth_config_id` (`ac_...`).

Record:

```text
COMPOSIO_SHOPIFY_AUTH_CONFIG_ID=ac_...
COMPOSIO_QBO_AUTH_CONFIG_ID=ac_...
COMPOSIO_SQUARE_AUTH_CONFIG_ID=ac_...
```

v1 uses Composio-managed configs only. See ADR-0134.

### 1.3 Link connected accounts (CLI)

Use Composio v3 `connected_accounts.link()`. Do **not** use deprecated `initiate()` for Composio-managed OAuth.

**Option A — one-off Node script** (recommended for reproducibility):

```javascript
// scripts/ops/composio-link.mjs (run locally; do not commit API keys)
import { Composio } from "@composio/core";

const composio = new Composio({ apiKey: process.env.COMPOSIO_API_KEY });

const USER_ID = "toee-staging"; // or toee-production
const AUTH_CONFIG_ID = process.env.COMPOSIO_SHOPIFY_AUTH_CONFIG_ID; // swap per toolkit

const request = await composio.connectedAccounts.link(USER_ID, AUTH_CONFIG_ID, {
  callbackUrl: "https://localhost/oauth/callback", // local callback is fine for ops-run link
});

console.log("Open this URL to authorize:", request.redirectUrl);
// After OAuth completes, read connected_account_id from callback query or Composio Dashboard
```

Run once per toolkit (Shopify, QBO, Square) and record each returned `connected_account_id`.

**Option B — Composio CLI**

If your Composio CLI version exposes `connected-accounts link`, prefer the SDK script above when CLI flags differ across versions. Use Dashboard to confirm the account reached **active** state.

### 1.4 Update Cloud Run environment

```bash
gcloud run services update toee-hermes-gateway \
  --region=REGION \
  --set-env-vars="INTEGRATION_DRIVER=composio,COMPOSIO_USER_ID=toee-staging,COMPOSIO_SHOPIFY_CONNECTED_ACCOUNT_ID=ca_...,COMPOSIO_QBO_CONNECTED_ACCOUNT_ID=ca_...,COMPOSIO_SQUARE_CONNECTED_ACCOUNT_ID=ca_..."
```

Deploy the revision and confirm env vars on the new revision before smoke.

## 2. First-time onboarding (production)

Repeat [section 1](#1-first-time-onboarding-staging) with these substitutions:

| Item | Production value |
|------|------------------|
| `COMPOSIO_USER_ID` | `toee-production` |
| Connected accounts | New `ca_...` values from a fresh link flow |
| Cloud Run service | Production `toee-hermes-gateway` (and workbench if applicable) |
| Smoke | Production smoke checklist after deploy; restrict side-effectful tests |

Never copy staging `connected_account_id` values into production.

## 3. Staging smoke

Smoke proves governed **Domain Adapter** actions work through the composio driver, not merely that OAuth succeeded.

### 3.1 Required Layer 1 actions

| Order | Tool.action | Purpose | Expected outcome |
|-------|-------------|---------|------------------|
| 1 | `toee_shopify_read.get_order` | Shopify connectivity | Governed order read succeeds for a known test order |
| 2 | `toee_qbo_read.get_invoice` | QBO connectivity + email-link gate | Succeeds only for verified customer with linked email |
| 3 | `toee_easyroutes_read.get_delivery_status` | Non-Composio regression | Still succeeds via direct driver |
| 4 | `toee_square_payment_link.send_payment_link` | Square connectivity | Staging only; use vendor sandbox or controlled test invoice |

### 3.2 Automated smoke (placeholder)

```bash
# TODO: replace when scripts/smoke or packages/eval-runner integration smoke exists
pnpm smoke:integrations -- --env staging
```

Until that command exists, use [manual smoke](#33-manual-smoke-until-runner-implements-integration-smoke).

### 3.3 Manual smoke (until Runner implements integration smoke)

1. Confirm Cloud Run revision has all `COMPOSIO_*` env vars and `INTEGRATION_DRIVER=composio`.
2. Trigger a staging **External Customer Service Profile** turn that causes `toee_shopify_read.get_order` (for example an SMS or internal adapter invoke path once available).
3. In **Cloud Logging**, verify:
   - no `error_class=configuration_missing`
   - no `error_class=auth_expired`
4. Confirm adapter audit records include `user_id`, toolkit `connected_account_id`, tool name, and v1 `action`.
5. Repeat for QBO read with a verified + email-linked fixture customer.

**Pass criteria:** Layer 1 reads succeed; failures return governed **Tool Unavailable Response**, not raw Composio errors to customers.

### 3.4 Layer 1 composio driver smoke (one read per tool)

This is the per-tool smoke for the Layer 1 `composio` driver (master Slice 30). The
driver sits behind exactly the three Layer 1 tools with strict one-to-one Composio
action mapping (ADR-0130); `mock` stays the default everywhere else (ADR-0137). It
performs the backend call and reshapes the vendor payload — the public `toee_*`
contracts are unchanged from the mock drivers.

**Required environment (on the active Cloud Run revision):**

| Variable | Example | Notes |
|----------|---------|-------|
| `INTEGRATION_DRIVER` | `composio` | Selects the Layer 1 composio driver; `mock` everywhere else |
| `COMPOSIO_API_KEY` | secret | From Secret Manager; missing key → governed `configuration_missing` |
| `COMPOSIO_USER_ID` | `toee-staging` | Fixed per environment |
| `COMPOSIO_SHOPIFY_CONNECTED_ACCOUNT_ID` | `ca_...` | Routes `toee_shopify_read` |
| `COMPOSIO_QBO_CONNECTED_ACCOUNT_ID` | `ca_...` | Routes `toee_qbo_read` |
| `COMPOSIO_SQUARE_CONNECTED_ACCOUNT_ID` | `ca_...` | Routes `toee_square_payment_link` |

**Steps:**

1. Connect Shopify, QuickBooks, and Square for this environment's `COMPOSIO_USER_ID`
   per [section 1.3](#13-link-connected-accounts-cli) (ADR-0133/0138), and confirm
   each connected account is **active** in the Composio Dashboard.
2. Confirm the Cloud Run revision carries `INTEGRATION_DRIVER=composio` plus all six
   variables above.
3. Run exactly one read per Layer 1 tool through a governed **External** turn and
   confirm governed output (not a raw vendor payload, not a customer-facing vendor
   error):
   - `toee_shopify_read.get_order` → Shopify connected account
   - `toee_qbo_read.get_invoice` → QBO connected account (verified + email-linked fixture)
   - `toee_square_payment_link.send_payment_link` → Square connected account
     (staging vendor sandbox or a controlled test invoice only)
4. In **Cloud Logging**, confirm each adapter audit record carries `user_id`, the
   toolkit `connected_account_id`, the v1 tool name, and the v1 `action` — and shows
   no `error_class=configuration_missing` / `auth_expired` on the success path.

**Verify the Composio action slugs here.** The slugs in the driver's one-to-one
mapping table (`hermes/toee_hermes/drivers/composio/driver.py`,
`ACTION_MAPPING` — e.g. `SHOPIFY_GET_ORDER`, `QUICKBOOKS_GET_INVOICE`,
`SQUARE_CREATE_PAYMENT_LINK`) are plausible placeholders. Confirm each against the
live Composio toolkit during this smoke, along with the SDK response envelope the
`_ComposioSdkClient` adapter unwraps, and correct any mismatch before go-live.

## 4. Reconnect on `auth_expired`

Triggered by ADR-0136 logs or alerts with `error_class=auth_expired` or `configuration_missing`.

### 4.1 Identify scope

From the log event, capture:

- environment (`toee-staging` vs `toee-production`)
- toolkit (`shopify`, `qbo`, `square`)
- previous `connected_account_id`

### 4.2 Re-link

1. Run `connected_accounts.link()` for the affected toolkit and `user_id` ([section 1.3](#13-link-connected-accounts-cli)).
2. Complete vendor OAuth again.
3. If Composio returns a **new** `connected_account_id`, update Cloud Run env.
4. Redeploy or roll to the updated revision.

### 4.3 Post-reconnect smoke

Rerun [staging smoke](#3-staging-smoke) for the affected toolkit actions only.

## 5. API key rotation

### 5.1 Rotate `COMPOSIO_API_KEY`

1. Create a new Composio API key in Composio Dashboard.
2. Add a new Secret Manager version for `composio-api-key`.
3. Update Cloud Run secret binding to the latest version.
4. Revoke the old Composio API key after services reload.

Connected account ids usually remain valid across API key rotation. If calls fail after rotation, check secret binding and service revision rollout first.

## Appendix A: Dashboard troubleshooting

Use Composio Dashboard when CLI output is unclear.

| Task | Dashboard location |
|------|-------------------|
| Find `auth_config_id` | Auth configs / Integrations |
| Confirm connected account is active | Connected accounts |
| Inspect failed OAuth | Connected account detail / logs |
| Revoke a bad connection | Disconnect account, then re-link |

**Common issues**

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| `configuration_missing` in logs | Missing env var on active revision | Fix Cloud Run env, redeploy |
| `auth_expired` after vendor password change | Stale connected account | Re-link toolkit ([section 4](#4-reconnect-on-auth_expired)) |
| QBO read blocked with email-link failure | Toee **Tool Gate**, not Composio | Fix Shopify/QBO customer email link; Composio may still be healthy |
| Staging hits live merchant data | Same vendor tenant in staging and production | Restrict staging smoke to read-only actions; document tenant mapping |

## Appendix B: Optional local developer link

For adapter development only. See ADR-0137.

1. Keep default `INTEGRATION_DRIVER=mock` in `.env.local`.
2. Create `COMPOSIO_USER_ID=toee-local-<your-name>`.
3. Link Shopify/QBO/Square with [section 1.3](#13-link-connected-accounts-cli) using your local user id.
4. Set `INTEGRATION_DRIVER=composio` and connected account ids in `hermes-runtime/.env` and/or workbench `.env.local` as needed.
5. Prefer read-only Layer 1 actions unless you have an explicit vendor sandbox.
6. Never reuse `toee-staging`, `toee-production`, or another developer's connected account ids.

**Launch Eval and CI always use mock drivers.** Do not load Composio credentials in CI.

## Quick checklist (中文)

**Staging 首次上线前**

- [ ] `COMPOSIO_API_KEY` 已写入 Secret Manager
- [ ] `toee-staging` 下 Shopify / QBO / Square 均已 link
- [ ] Cloud Run env 含三个 `CONNECTED_ACCOUNT_ID` 且 `INTEGRATION_DRIVER=composio`
- [ ] Smoke：`get_order`、`get_invoice` 无 `auth_expired` / `configuration_missing`
- [ ] Production 使用独立 `toee-production` 与独立 `ca_...` 重复上述步骤

**断连告警后**

- [ ] 确认环境与 toolkit → re-link → 更新 env → 重跑 smoke
