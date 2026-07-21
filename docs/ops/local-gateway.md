# Local SMS Gateway (SimpleTexting) — inbound SMS simulation

Simulate **customer inbound SMS** on your machine: SimpleTexting webhook → Python Gateway →
ingress match → in-memory persist → async **External Customer Service Profile** agent turn.
This is **not** the Workbench copilot chat path (`pnpm dev:workbench`).

Cloud Run / Cloud Tasks wiring (Slice 37, issue #40) is out of scope here.

See also: [`local-e2e.md`](local-e2e.md) (Workbench Tier B), [`deploy-cloud-run.md`](deploy-cloud-run.md) (production smoke).

---

## Why `pnpm dev:gateway` is a stub

Root `package.json` runs `pnpm --filter @toee/hermes-gateway dev`, which prints a placeholder
(`services/hermes-gateway/package.json`). The live gateway is the **Python FastAPI app** in
`hermes-runtime/` (ADR-0095). Boot it with **uvicorn** (below), not pnpm.

---

## Prerequisites

One-time from repo root:

```powershell
cd hermes-runtime; uv sync; cd ..
```

Create `hermes-runtime/.env` (gitignored). **`build_gateway_app` fails closed** if any
required variable is missing. Copy names from repo-root [`.env.example`](../../.env.example);
use your own values — never commit secrets.

| Variable | Required | Purpose |
| --- | --- | --- |
| `SIMPLETEXTING_WEBHOOK_TOKEN` | yes | Shared token in the inbound `/webhooks/simpletexting?token=…` URL (ADR-0021) |
| `INTERNAL_JOB_SECRET` | yes | Shared secret for `/internal/jobs/agent-turn` (ADR-0106) |
| `SIMPLETEXTING_API_TOKEN` | yes | Outbound SimpleTexting sends (opt-out + agent turn, ADR-0083) |
| `OPENROUTER_API_KEY` | yes | Live LLM for the async agent turn (ADR-0009) |
| `TOOL_BACKEND` | for Workbench queue | Set to `datastore` so inbound SMS persists to Postgres and appears in the Workbench copilot queue (same DB as Tier B). Requires `docker compose up -d postgres` + migrations. |
| `DATABASE_URL` | with `datastore` | Defaults to `postgresql://toee:toee@localhost:5432/toee_va` when unset. |

Optional overrides (defaults are fine locally): `SIMPLETEXTING_API_BASE_URL`, `SIMPLETEXTING_ACCOUNT_PHONE`, `OPENROUTER_BASE_URL`,
`OPENROUTER_MODEL`, `OPENROUTER_FALLBACK_MODEL`.

---

## Terminal layout

The gateway is a **separate process** from Workbench and dispatch servers. Typical local layout:

| Terminal | Service | Port (example) |
| --- | --- | --- |
| A | Postgres (`docker compose up -d postgres`) | 5432 — optional for gateway smoke |
| B | **Gateway** (this runbook) | **8080** |
| C | Workbench (`pnpm dev:workbench`) | 3000 — unrelated to inbound SMS sim |
| D–E | Tool-dispatch servers (`scripts/run-dispatch-server.ps1`) | 8081 / 8082 — not used by default gateway boot |

The gateway uses the **mock integration driver** by default (`MockDriver` in `create_app`).
Identity ingress resolves against mock fixtures (verified test phone `+14165550101`).

---

## Boot the gateway

From repo root (PowerShell):

```powershell
cd hermes-runtime
uv run uvicorn hermes_runtime.gateway_composition:build_gateway_app --factory --host 127.0.0.1 --port 8080
```

Smoke the liveness route (no auth):

```powershell
Invoke-RestMethod http://127.0.0.1:8080/healthz
# expect: status = ok
```

Production uses the same factory; Cloud Run sets `--host 0.0.0.0` and `$PORT` (see
`hermes-runtime/Dockerfile`).

---

## Simulate inbound SMS (no real SimpleTexting)

**Route:** `POST /webhooks/simpletexting?token=<SIMPLETEXTING_WEBHOOK_TOKEN>`  
No signature header — SimpleTexting authenticates via the shared URL token (ADR-0021).

### Helper script (recommended)

From repo root, with the gateway running:

```powershell
powershell -NoProfile -File scripts/simulate-simpletexting-webhook.ps1 -Token "<your-webhook-token>" -Body "Do you have 225/65R17 in stock?" -ContactPhone "+14165550101"
```

Optional: `-GatewayUrl http://127.0.0.1:8080`, `-AccountPhone 9053378266`, `-MessageId evt-local-1`.

Re-running with the same `-MessageId` is a no-op ack: dedup keys on `messageId`, and
an opt-out (`STOP`) sends its confirmation exactly once (ADR-0016). Vary `-MessageId`
to simulate a genuinely new message.

### Manual PowerShell (one inbound)

```powershell
$token = $env:SIMPLETEXTING_WEBHOOK_TOKEN
$bodyObj = @{
  reportId  = "rep-manual-1"
  webhookId = "wh-manual"
  type      = "INCOMING_MESSAGE"
  values    = @{
    messageId    = "evt-manual-1"
    text         = "Do you have 225/65R17 in stock?"
    accountPhone = "9053378266"
    contactPhone = "+14165550101"
    timestamp    = "2026-01-01T00:00:00.000Z"
    category     = "SMS"
  }
}
$body = ($bodyObj | ConvertTo-Json -Depth 4 -Compress)
$uri = "http://127.0.0.1:8080/webhooks/simpletexting?token=$([uri]::EscapeDataString($token))"
Invoke-WebRequest -Method POST -Uri $uri -ContentType "application/json" -Body $body
```

Use a **compact JSON body** for signing; whitespace changes invalidate the signature.

---

## Expected HTTP outcomes

| Case | Status | Gateway behavior |
| --- | --- | --- |
| Missing / wrong signature | **401** | Rejected before processing |
| Normal inbound (e.g. stock question) | **200** | Persist + enqueue async agent turn |
| Opt-out keyword (`STOP`, etc.) | **200** | Fixed compliance reply via SimpleTexting; **no** agent turn |
| Duplicate `event_id` (when idempotency wired) | **200** | No-op ack |
| Rate-limited sender | **200** | Persist snapshot; **no** enqueue |
| Transient identity lookup failure | **500** | Retryable ingress error |

After a **200 enqueue**, `LocalDispatchingJobQueue` runs the agent turn on a **background
thread** (fast-ack, ADR-0103). You do **not** need to call `/internal/jobs/agent-turn`
manually in local mode — that route exists for Cloud Tasks parity (ADR-0106).

---

## What store is used today

When ``TOOL_BACKEND=datastore`` (recommended for Tier B + real inbound), ``build_gateway_app`` wires **`PostgresGatewayStore`** and **`PostgresDriver`** for ingress identity lookup. Accepted inbound turns write `customer_thread`, `sms_session`, `message_turn`, `session_identity_snapshot`, `agent_turn_context`, and an **open Follow-up Case** into the same Postgres database the Workbench BFF reads.

When ``TOOL_BACKEND`` is unset or ``mock`` (default), the gateway uses **`InMemoryGatewayStore`** — inbound SMS does **not** appear in the Workbench queue.

**Honest limits (unchanged):**

- Restarting an **in-memory** gateway drops context; Postgres mode survives restarts.
- **Identity lookup** with `datastore` reads `identity_link` in Postgres first. When
  `INTEGRATION_DRIVER=composio` and Shopify is linked, ingress falls back to a
  Composio Shopify customer phone lookup and auto-writes `identity_link` on a
  single match. Without a Shopify registered phone on file, inbound still acks as
  *Unmatched Caller*. Manual seed (below) remains valid for dev overrides.
- The async agent turn still routes **business tools** through the plugin's `INTEGRATION_DRIVER` (mock/composio), not `TOOL_BACKEND`. Case rows for inbound are opened at persist time so Workbench shows the thread immediately; agent `create_case` during the turn still uses mock unless you wire Composio + future composite driver work.
- A **live agent reply** needs a valid `OPENROUTER_API_KEY` (LLM) and, for outbound SMS, a working `SIMPLETEXTING_API_TOKEN` (the conversation_id is the contact's E.164 phone).
- Cloud Tasks replace `LocalDispatchingJobQueue` in a later slice (#40).

### Tier B: gateway + Workbench on the same Postgres

1. Start Postgres and migrate (see [`local-e2e.md`](local-e2e.md) Terminal 1).
2. Start dispatch servers + Workbench (Terminals 2–4) with `TOOL_BACKEND=datastore`.
3. In `hermes-runtime/.env`, set:

   ```bash
   TOOL_BACKEND=datastore
   # DATABASE_URL=postgresql://toee:toee@localhost:5432/toee_va
   ```

4. Boot the gateway (same env as dispatch):

   ```powershell
   cd hermes-runtime
   uv run uvicorn hermes_runtime.gateway_composition:build_gateway_app --factory --host 127.0.0.1 --port 8080
   ```

   For Shopify ingress phone match, set
   `COMPOSIO_TOOLKIT_VERSION_SHOPIFY=20260506_00` (or newer) in `hermes-runtime/.env`
   so Composio exposes `SHOPIFY_GET_CUSTOMERS_SEARCH`. The placeholder `00000000_00`
   toolkit only lists customers and cannot search by phone.

5. Simulate or receive inbound SMS (below). Open Workbench copilot queue — a new case with the inbound preview should appear (alongside any `0005_dev_bootstrap` demo cases unless you delete them).

#### Optional: real customer identity (Postgres)

```sql
INSERT INTO identity_link (id, channel, channel_identity, shopify_customer_id, match_status)
VALUES ('link_real_1', 'sms', '+1YOUR_CUSTOMER_E164', 'gid://shopify/Customer/YOUR_ID', 'verified')
ON CONFLICT DO NOTHING;
```

Replace `+1YOUR_CUSTOMER_E164` with the inbound `contactPhone` (E.164). Without this row, ingress still acks but `identity_summary` shows the raw phone.

#### Optional: hide demo seed cases

Migration `0005_dev_bootstrap` seeds `case_ar_urgent` and `case_toolfail`. To work with real inbound only:

```sql
DELETE FROM cases WHERE id IN ('case_ar_urgent', 'case_toolfail');
DELETE FROM message_turn WHERE customer_thread_id IN ('thread_ar', 'thread_toolfail');
DELETE FROM sms_session WHERE customer_thread_id IN ('thread_ar', 'thread_toolfail');
DELETE FROM customer_thread WHERE id IN ('thread_ar', 'thread_toolfail');
```

Accounts (`rep` / `admin`) remain; only demo queue rows are removed.

### Point the SimpleTexting webhook at the local gateway

SimpleTexting must reach your machine on `/webhooks/simpletexting`:

1. Boot gateway on port **8080** (above).
2. Expose with a tunnel, e.g. [ngrok](https://ngrok.com/): `ngrok http 8080`
3. Register the webhook (API `POST /api/webhooks` or dashboard Integrations → Webhooks) with URL `https://<tunnel-host>/webhooks/simpletexting?token=<SIMPLETEXTING_WEBHOOK_TOKEN>` and trigger `INCOMING_MESSAGE`.
4. Set `SIMPLETEXTING_WEBHOOK_TOKEN` in `hermes-runtime/.env` to the **same token** embedded in that URL.

Production: deploy gateway to Cloud Run and point the SimpleTexting webhook at the service URL (see [`deploy-cloud-run.md`](deploy-cloud-run.md)).

---

## Previous in-memory-only note (superseded when TOOL_BACKEND=datastore)

When using the default mock backend, `build_gateway_app` wired **`InMemoryGatewayStore`** only:

**Honest limits:**

- Inbound SMS simulation **did not** appear in the Workbench Postgres copilot queue.
- Restarting the gateway **dropped** in-memory context.

---

## Tests

```powershell
cd hermes-runtime
uv run pytest tests/test_gateway_app.py tests/test_gateway_composition.py tests/test_gateway_healthz.py -q
```

Signature crypto unit tests live under `hermes/tests/test_gateway_verify.py`.
