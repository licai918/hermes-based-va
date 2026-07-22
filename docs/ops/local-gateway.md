# Local Textline Gateway — inbound SMS simulation

Simulate **customer inbound SMS** on your machine: Textline webhook → Python Gateway →
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
| `TEXTLINE_WEBHOOK_SECRET` | yes | HMAC key for inbound `/webhooks/textline` (ADR-0021) |
| `INTERNAL_JOB_SECRET` | yes | Shared secret for `/internal/jobs/agent-turn` (ADR-0106) |
| `TEXTLINE_ACCESS_TOKEN` | yes | Outbound Textline replies (opt-out + agent turn, ADR-0083) |
| `OPENROUTER_API_KEY` | yes | Live LLM for the async agent turn (ADR-0009) |
| `TOOL_BACKEND` | for Workbench queue | Set to `datastore` so inbound SMS persists to Postgres and appears in the Workbench copilot queue (same DB as Tier B). Requires `docker compose up -d postgres` + migrations. |
| `DATABASE_URL` | with `datastore` | Defaults to `postgresql://toee:toee@localhost:5432/toee_va` when unset. |
| `TEXTLINE_MAX_SIGNATURE_AGE_SECONDS` | recommended in prod | Opt-in TGP replay window. The live TGP signature covers only `event_type + event_time + secret` (not the body, no expiry), so a leaked `(signature, time, type)` triple can be replayed. Set to reject events whose `X-Tgp-Event-Time` is outside ±N seconds of now. Suggested: `900` (15 min — covers Textline retries without leaving an open replay window). Unset = no freshness check. |

Optional overrides (defaults are fine locally): `TEXTLINE_API_BASE_URL`, `OPENROUTER_BASE_URL`,
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

## Simulate inbound SMS (no real Textline)

**Route:** `POST /webhooks/textline`  
**Header:** `X-Textline-Signature` = HMAC-SHA256 hex digest of the **exact raw JSON body**,
keyed by `TEXTLINE_WEBHOOK_SECRET` (ADR-0021).

### Helper script (recommended)

From repo root, with the gateway running:

```powershell
$env:TEXTLINE_WEBHOOK_SECRET = '<your-webhook-secret>'
powershell -NoProfile -File scripts/simulate-textline-webhook.ps1 -Body "Do you have 225/65R17 in stock?" -From "+14165550101"
```

Optional: `-GatewayUrl http://127.0.0.1:8080`, `-ConversationId conv-local-1`, `-EventId evt-local-1`.

### Manual PowerShell (one inbound)

```powershell
$secret = $env:TEXTLINE_WEBHOOK_SECRET
$bodyObj = @{
  id = "evt-manual-1"
  conversation_id = "conv-manual-1"
  from = "+14165550101"
  body = "Do you have 225/65R17 in stock?"
  received_at = "2026-01-01T00:00:00Z"
  type = "message.created"
}
$body = ($bodyObj | ConvertTo-Json -Compress)
$hmac = [System.Security.Cryptography.HMACSHA256]::new([Text.Encoding]::UTF8.GetBytes($secret))
$sig = -join ($hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($body)) | ForEach-Object { $_.ToString("x2") })
Invoke-WebRequest -Method POST -Uri "http://127.0.0.1:8080/webhooks/textline" `
  -ContentType "application/json" `
  -Headers @{ "X-Textline-Signature" = $sig } `
  -Body $body
```

Use a **compact JSON body** for signing; whitespace changes invalidate the signature.

---

## Expected HTTP outcomes

| Case | Status | Gateway behavior |
| --- | --- | --- |
| Missing / wrong signature | **401** | Rejected before processing |
| Normal inbound (e.g. stock question) | **200** | Persist + enqueue async agent turn |
| Opt-out keyword (`STOP`, etc.) | **200** | Fixed compliance reply via Textline; **no** agent turn |
| Duplicate `event_id` (when idempotency wired) | **200** | No-op ack |
| Rate-limited sender | **200** | Persist snapshot; **no** enqueue |
| Transient identity lookup failure | **500** | Retryable ingress error |

After a **200 enqueue** the gateway has written one row to the durable `job` table and
returned (fast-ack, ADR-0103/ADR-0153). **The turn does not run in the gateway process
any more** — you must also be running the turn worker:

```bash
docker compose up -d postgres turn-worker
# or, on the host:
cd hermes-runtime && uv run python -m hermes_runtime.turn_worker
```

It claims `agent_turn` jobs (only that type — FR-9), runs the same bound turn the
gateway used to run inline, and completes the job. Kill it mid-turn and the job is
reclaimed on a later poll and re-run, which is the whole point of the cutover. You
do **not** need to call `/internal/jobs/agent-turn` manually — that route survives
for ADR-0106 parity only.

Requires `TOOL_BACKEND=datastore`: the worker reloads the context the gateway
persisted (ADR-0107), and two processes can only share it through Postgres.

### The background worker (0.0.4 S04)

A **second** worker runs every non-turn job — the L6 learning fork, the Customer
Memory retention sweep, and the knowledge corpus re-ingest:

```bash
docker compose up -d postgres background-worker
# or, on the host:
cd hermes-runtime && uv run python -m hermes_runtime.background_worker
```

It claims `l6_review`, `retention` and `ingest` — never `agent_turn`. The two
allowlists are disjoint, which is why a corpus re-ingest that runs for minutes
cannot queue ahead of a waiting customer (FR-9). Same `TOOL_BACKEND=datastore`
boot requirement, same reason.

**It also runs the schedule tick.** There is no cron in this repo: if this
process is not up, the retention sweep never runs on its daily cadence (the admin
panel's button still queues one, but nothing will claim it either). Set
`INGEST_CORPUS_PATH` on it to point at the Stage A pull artifact, or a queued
re-ingest fails naming that variable rather than wiping the corpus.

**Environment that must match the dispatch/copilot process.** An `l6_review` job is
*enqueued* by whichever process runs the copilot turn and *executed* here, so
`AGENT_EXPERIENCE_LEARNING` and `OPENROUTER_API_KEY` are needed on **both**. Both
are default OFF/unset and no `l6_review` job exists while the flag is off, so
neither is required today. The day you turn the L6 learning loop on, turn it on for
this worker too: a job that reaches a worker with the flag off (or with no key)
fails with `L6ReviewMisconfigured` and dead-letters, instead of quietly reporting
success without writing the `agent_experience` row the loop exists for. Both
variables are named (commented out) in the `background-worker` compose service.

---

## What store is used today

When ``TOOL_BACKEND=datastore`` (recommended for Tier B + real inbound), ``build_gateway_app`` wires **`PostgresGatewayStore`** and **`PostgresDriver`** for ingress identity lookup. Accepted inbound turns write `customer_thread`, `sms_session`, `message_turn`, `session_identity_snapshot`, `agent_turn_context`, and an **open Follow-up Case** into the same Postgres database the Workbench BFF reads.

When ``TOOL_BACKEND`` is unset or ``mock``, ``build_gateway_app()`` **raises at boot** (0.0.4 S02 fix wave 1). The turn runs in a separate worker process, which cannot see another process's in-memory store, so that configuration could only ack webhooks and silently never reply — the exact failure this composition root's fail-closed posture exists to prevent. ``create_app()`` still defaults to **`InMemoryGatewayStore`** for DB-free tests, which build the app directly.

**Honest limits (unchanged):**

- Restarting an **in-memory** gateway drops context; Postgres mode survives restarts.
- **Identity lookup** with `datastore` reads `identity_link` in Postgres first. When
  `INTEGRATION_DRIVER=composio` and Shopify is linked, ingress falls back to a
  Composio Shopify customer phone lookup and auto-writes `identity_link` on a
  single match. Without a Shopify registered phone on file, inbound still acks as
  *Unmatched Caller*. Manual seed (below) remains valid for dev overrides.
- The async agent turn still routes **business tools** through the plugin's `INTEGRATION_DRIVER` (mock/composio), not `TOOL_BACKEND`. Case rows for inbound are opened at persist time so Workbench shows the thread immediately; agent `create_case` during the turn still uses mock unless you wire Composio + future composite driver work.
- A **live agent reply** needs a valid `OPENROUTER_API_KEY` (LLM) and, for outbound SMS, a working `TEXTLINE_ACCESS_TOKEN` + real `conversation_id`.
- With `TOOL_BACKEND` unset the production gateway does not boot at all: it fails
  closed rather than acking webhooks it can never reply to.

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

Replace `+1YOUR_CUSTOMER_E164` with the Textline `from` phone (E.164). Without this row, ingress still acks but `identity_summary` shows the raw phone.

#### Optional: hide demo seed cases

Migration `0005_dev_bootstrap` seeds `case_ar_urgent` and `case_toolfail`. To work with real inbound only:

```sql
DELETE FROM cases WHERE id IN ('case_ar_urgent', 'case_toolfail');
DELETE FROM message_turn WHERE customer_thread_id IN ('thread_ar', 'thread_toolfail');
DELETE FROM sms_session WHERE customer_thread_id IN ('thread_ar', 'thread_toolfail');
DELETE FROM customer_thread WHERE id IN ('thread_ar', 'thread_toolfail');
```

Accounts (`rep` / `admin`) remain; only demo queue rows are removed.

### Point Textline webhook at local gateway

Textline must reach your machine on `/webhooks/textline`:

1. Boot gateway on port **8080** (above).
2. Expose with a tunnel, e.g. [ngrok](https://ngrok.com/): `ngrok http 8080`
3. In Textline Developer settings, set webhook URL to `https://<tunnel-host>/webhooks/textline`.
4. Set `TEXTLINE_WEBHOOK_SECRET` in `hermes-runtime/.env` to the **same secret** Textline uses to sign payloads.

Production: deploy gateway to Cloud Run and point Textline at the service URL (see [`deploy-cloud-run.md`](deploy-cloud-run.md)). The old Cloud Run URL returning 404 is a different (legacy) service — update Textline to the new gateway URL.

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
