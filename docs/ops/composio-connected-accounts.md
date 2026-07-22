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

### 3.2 Automated smoke

```bash
# From the deployment environment (or a box carrying the same hermes-runtime/.env):
cd hermes-runtime && uv run python -m hermes_runtime.composio_smoke
```

Four phases; exits non-zero on any FAIL (0.0.4 S12):

1. **config** — `INTEGRATION_DRIVER`, the three connected accounts, and the three
   **required** toolkit version pins.
2. **surface** — every mapped action slug resolves against the live toolkit *at
   its pinned version*. This is what catches "the pin is a real version but the
   action is not in it" before a customer does.
3. **happy path** — one governed identity-scoped read per tool through
   `execute_tool`, asserting the public contract shape. Needs
   `SMOKE_SHOPIFY_CUSTOMER_ID` (the PAC-6 test customer, §6.3); without it those
   checks print SKIP and the run is not a pass.
4. **fail-closed** — the same calls with the backend unreachable: a governed
   `composio_api_error` inside the driver deadline (NFR-8), and explicitly **not**
   the mock payload (FR-21).

There is no mocked mode, on purpose: a smoke that can go green without a backend
is not evidence of a cutover.

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

**The action slugs are pinned as of 0.0.4 S12** — they are no longer placeholders.
`python -m hermes_runtime.composio_smoke` phase 2 resolves every slug in
`ACTION_MAPPING` against the live toolkit at its pinned version, and
`hermes-runtime/tests/test_composio_sdk_pin.py` holds the SDK call surface and
response envelope in CI. Re-run the smoke after any toolkit-version bump or SDK
upgrade; that is what "pinned" buys you.

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

## 6. Production cutover checklist (0.0.4 S12, FR-18)

### 6.1 Every process that executes tools — not just the gateway

The cutover surface is wider than "the gateway". Five processes reach a Composio
toolkit, and a revision that sets `INTEGRATION_DRIVER=composio` on only some of
them is a split brain: the same customer gets live data on one path and mock data
on another.

| Process | Why it calls Composio | Local (`docker-compose.yml`) |
|---------|----------------------|------------------------------|
| **gateway** | Ingress Phone Match falls back to a live Shopify customer lookup (`hermes_runtime/datastore/shopify_identity.py`) | `gateway` |
| **turn worker** | Runs the customer's async agent turn — this is where `toee_shopify_read` / `toee_qbo_read` actually execute | `turn-worker` |
| **dispatch server (copilot, 8091)** | Its `agent:turn` LLM draft route boots a profile per turn, and THAT reaches Composio. Its `tools:dispatch` route does not — that one uses `select_tool_driver()` (the `TOOL_BACKEND` axis) | `dispatch-copilot` |
| **dispatch server (admin, 8092)** | `tools:dispatch` only, so it never reaches Composio today. Set the variables anyway: the fleet must not go split-brain when a later slice mounts a turn route here, and a uniform env is what makes the rollback in §6.4 one action | `dispatch-admin` |
| **background worker** | Shares the image and the `l6_review` fork's tool surface | `background-worker` |

Locally all five inherit `hermes-runtime/.env` through the `x-hermes-runtime`
anchor, so one file covers them. **On Cloud Run each is its own service and each
needs the variables set independently.**

### 6.2 Per-service variables

Required on **every** service in the table above:

| Variable | Source | Notes |
|----------|--------|-------|
| `INTEGRATION_DRIVER=composio` | plain env | |
| `COMPOSIO_API_KEY` | Secret Manager | |
| `COMPOSIO_USER_ID` | plain env | |
| `COMPOSIO_{SHOPIFY,QBO,SQUARE}_CONNECTED_ACCOUNT_ID` | plain env | |
| `COMPOSIO_TOOLKIT_VERSION_SHOPIFY` | plain env | **required** — boot fails without it |
| `COMPOSIO_TOOLKIT_VERSION_QUICKBOOKS` | plain env | **required**; note `QUICKBOOKS`, not `QBO` |
| `COMPOSIO_TOOLKIT_VERSION_SQUARE` | plain env | **required** |
| `COMPOSIO_DEADLINE_MS` | plain env | optional; defaults to 8000 (NFR-8) |
| `TOOL_BACKEND=datastore` | plain env | pre-existing boot requirement |

The version-pin variables are keyed by **Composio's** toolkit slug, not ours:
`COMPOSIO_TOOLKIT_VERSION_QBO` is silently ignored.

A missing or `latest` pin fails the process at **boot**, naming the variable.
That is enforced by `require_composio_configuration()`, called from each of the
four composition roots (`build_gateway_app`, `turn_worker.main`,
`background_worker.main`, `build_tool_dispatch_app`) — 0.0.4 S12 fix wave 1.
Before that call existed the driver was built per `boot_profile()`, i.e. per
TURN, so a bad pin produced a clean boot followed by a raw exception on the
first customer message. If you are on a revision that predates it, expect the
failure on first traffic, not at startup.

### 6.3 PAC-6 test data (owner action)

Before a PAC drill runs against the live store:

1. Create a **dedicated test customer** in the live Shopify store with a phone
   number that is not a real customer's.
2. Give it a test order, and a matching test invoice in QuickBooks.
3. Set `SMOKE_SHOPIFY_CUSTOMER_ID=gid://shopify/Customer/<id>` in the deployment
   env (smoke happy path).
4. Set `NEXT_PUBLIC_SIM_VERIFIED_PHONE=<phone>` for the simulator's "verified"
   preset. **Where depends on how the workbench runs** — `NEXT_PUBLIC_*` is
   inlined by Next.js at **build** time, not read at runtime (0.0.4 S12 fix
   wave 1):
   - **local `next dev` / `pnpm dev`** — `apps/workbench/.env.local`, then
     restart the dev server.
   - **deployed workbench (Cloud Run)** — it must be present when the image is
     BUILT. Setting it on the running service does nothing; the value is already
     baked into the client bundle. Pass it as a build arg / build-time env in the
     workbench image build and redeploy.

Until step 3, the smoke's happy-path checks SKIP. Until step 4, the simulator's
verified preset still points at the mock-seeded `+14165550101`, which resolves
`unmatched_caller` against a live store — the PAC drill has no verified path.
The preset's LABEL tells you which value the running bundle carries: "Verified
customer (seeded)" vs "(live test entity)".

### 6.4 Order of operations

1. Link/verify all three connected accounts (§1.3) and confirm **active**.
2. Set the variables in §6.2 on every service in §6.1.
3. Run `python -m hermes_runtime.composio_smoke` from one of them; require PASS.
4. Roll the services. A misconfigured pin now fails the process at startup with
   `configuration_missing` naming the variable, so a service that comes up
   healthy has a valid Composio config — that is what step 2 buys. Watch the
   startup logs, not the first turn.
5. Roll back = `INTEGRATION_DRIVER=mock` on every service in §6.1, together.

### 6.5 Known gap: Square payment links

Composio's Square toolkit has **no create-payment-link action** at any version
(verified 0.0.4 S12: only `SQUARE_RETRIEVE_PAYMENT_LINK` exists, and a
catalog-wide search finds no Square create action). The owner's 0.0.4 S26 decision
switched the tool to **retrieve** semantics — links are pre-created in the Square
console and the agent only fetches and sends an existing one — and S26's live
probe confirms `SQUARE_RETRIEVE_PAYMENT_LINK` resolves at pin `20260616_00` with
exactly one parameter, `{"required": ["id"]}`.

`toee_square_payment_link` **still fails closed** with a governed
`configuration_missing`, so a customer is never sent a fabricated or mock link.
What is missing is no longer the action but the link's identity: retrieve is by
the Square-assigned payment link id, nothing the agent legitimately holds maps to
one, and there is no list/search action at the pin to resolve one
(`SQUARE_LIST_PAYMENT_LINKS` 404s).

**To turn this on, the owner must decide and supply:**

1. **How a link is identified** — one fixed link for all payments, or one
   pre-created link per invoice. Either way the runtime needs the Square-assigned
   **ids**, not the console URLs; a console naming convention alone does not work,
   because nothing at the pin can look a name up.
2. **Whether the amount must be confirmed before send** (ADR-0066 says it must).
   A retrieved payment link carries no money field — only `orderId` — so a
   confirmed amount needs a second Square call, which ADR-0130 currently forbids
   for one v1 action.
3. **`ORDERS_READ` on the Square connected account.** S26's live execute came back
   `INSUFFICIENT_SCOPES` for `ORDERS_READ` — and Composio reported that vendor
   error as `successful: true` with a null link, so a naive response mapper would
   turn it into an empty "result" instead of a failure. Re-authorize the Square
   connection with `ORDERS_READ` before enabling the path.

The Square connected account is required for the smoke's other checks regardless.

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
