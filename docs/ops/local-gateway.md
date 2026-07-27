# Local SMS Gateway (SimpleTexting) — inbound SMS simulation

Simulate **customer inbound SMS** on your machine: tokened webhook → Python Gateway →
ingress match → Postgres persist + one durable `job` row → **turn worker** runs the
async **External Customer Service Profile** agent turn. This is **not** the
Workbench copilot chat path.

Cloud Run / Cloud Tasks wiring (Slice 37, issue #40) is out of scope here.

See also: [`apps/workbench/README.md`](../../apps/workbench/README.md) (the
`pnpm dev` stack this runs inside), [`local-e2e.md`](local-e2e.md) (verification
checklist), [`deploy-cloud-run.md`](deploy-cloud-run.md) (production smoke).

---

## Boot the gateway

```bash
pnpm dev
```

As of 0.0.4 S10 the gateway is a `docker compose` service (`gateway`, port 8080)
and comes up with the rest of the stack — together with the **turn worker**, which
is the process that actually runs the inbound turn. Nothing here needs a
hand-started uvicorn or a spare terminal. (The live gateway is the Python
FastAPI app in `hermes-runtime/`, ADR-0095.)

Smoke the liveness route (no auth):

```powershell
Invoke-RestMethod http://127.0.0.1:8080/healthz
# expect: status = ok
```

Production uses the same factory; Cloud Run sets `--host 0.0.0.0` and `$PORT` (see
`hermes-runtime/Dockerfile`).

To iterate on gateway code against the host venv instead, stop the container
(`docker compose stop gateway`) and run `pwsh scripts/run-gateway.ps1`.

---

## Environment

`build_gateway_app` **fails closed**: a missing required variable raises at boot
rather than acking a webhook it can never answer. Compose supplies the first three
rows; the rest come from `hermes-runtime/.env` (gitignored — copy names from
repo-root [`.env.example`](../../.env.example), never commit secrets).

| Variable | Supplied by | Purpose |
| --- | --- | --- |
| `TOOL_BACKEND=datastore` | compose | Boot requirement (0.0.4 S02). The gateway persists the turn context and a *separate* worker reloads it; no other backend can cross that gap. |
| `DATABASE_URL` / `KNOWLEDGE_DATABASE_URL` | compose | In-network DSNs for the two databases. |
| `REPLY_SENDER` | compose (`simulated`) | Skips the real provider POST — no `SIMPLETEXTING_API_TOKEN` needed and a dev box can never text a real customer — while still mirroring the reply into `message_turn`. Set `simpletexting` in `hermes-runtime/.env` (plus a token) to send for real. Any other value fails closed at boot. |
| `SIMPLETEXTING_WEBHOOK_TOKEN` | `hermes-runtime/.env` if set, else `apps/workbench/.env.local`'s dev default, passed through by `pnpm dev` | Shared token in the inbound `/webhooks/simpletexting?token=…` URL (ADR-0153). SimpleTexting does not sign payloads, so this is the only inbound credential — it must match the registered URL or every inbound is a 401. `pnpm dev` logs which file won. |
| `INTERNAL_JOB_SECRET` | `hermes-runtime/.env` | Shared secret for `/internal/jobs/agent-turn` (ADR-0106). |
| `OPENROUTER_API_KEY` | `hermes-runtime/.env` | Live LLM for the async agent turn (ADR-0009). |
| `SIMPLETEXTING_API_TOKEN` | `hermes-runtime/.env` | Only with `REPLY_SENDER=simpletexting`. |

Optional overrides (defaults are fine locally): `SIMPLETEXTING_API_BASE_URL`,
`SIMPLETEXTING_ACCOUNT_PHONE`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL`,
`OPENROUTER_FALLBACK_MODEL`.

Identity ingress resolves against mock fixtures with the mock driver (verified test
phone `+14165550101`); with `INTEGRATION_DRIVER=composio` it reads `identity_link`
in Postgres first and falls back to a Shopify phone lookup.

### The easy way in: the workbench simulator

`/copilot/simulator` posts a tokened webhook to this gateway
(`SIMULATOR_GATEWAY_URL`), so the whole inbound path runs without any curl or
hand-built payload — and it reads the reply back out of `message_turn`. That is the
recommended local exercise; the raw recipes below are for debugging the webhook
contract itself.

---

## Simulate inbound SMS (no real SimpleTexting)

**Route:** `POST /webhooks/simpletexting?token=<SIMPLETEXTING_WEBHOOK_TOKEN>`  
There is no signature header and no body-signature scheme at all — SimpleTexting does
not sign webhooks, so the only inbound credential is the shared URL token, and replay
protection is `messageId` idempotency (ADR-0153).

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

---

## Expected HTTP outcomes

| Case | Status | Gateway behavior |
| --- | --- | --- |
| Missing / wrong `token` | **401** | Rejected before processing |
| Normal inbound (e.g. stock question) | **200** | Persist + enqueue async agent turn |
| Opt-out keyword (`STOP`, etc.) | **200** | Fixed compliance reply via SimpleTexting; **no** agent turn |
| Duplicate `messageId` | **200** | No-op ack (`claim_event` compare-and-set; ADR-0016/0153) |
| Rate-limited sender | **200** | Persist snapshot; **no** enqueue |
| Transient identity lookup failure | **500** | Retryable ingress error |

After a **200 enqueue** the gateway has written one row to the durable `job` table and
returned (fast-ack, ADR-0103/ADR-0155). **The turn does not run in the gateway process
any more** — the turn worker must also be running. `pnpm dev` starts it; on its own:

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

When ``TOOL_BACKEND=datastore`` (the default under `pnpm dev`, and required for real inbound), ``build_gateway_app`` wires **`PostgresGatewayStore`** and **`PostgresDriver`** for ingress identity lookup. Accepted inbound turns write `customer_thread`, `sms_session`, `message_turn`, `session_identity_snapshot`, `agent_turn_context`, and an **open Follow-up Case** into the same Postgres database the Workbench BFF reads.

When ``TOOL_BACKEND`` is unset or ``mock``, ``build_gateway_app()`` **raises at boot** (0.0.4 S02 fix wave 1). The turn runs in a separate worker process, which cannot see another process's in-memory store, so that configuration could only ack webhooks and silently never reply — the exact failure this composition root's fail-closed posture exists to prevent. ``create_app()`` still defaults to **`InMemoryGatewayStore`** for DB-free tests, which build the app directly.

**Honest limits (unchanged):**

- Restarting an **in-memory** gateway drops context; Postgres mode survives restarts.
- **Identity lookup** with `datastore` reads `identity_link` in Postgres first. When
  `INTEGRATION_DRIVER=composio` and Shopify is linked, ingress falls back to a
  Composio Shopify customer phone lookup and auto-writes `identity_link` on a
  single match. Without a Shopify registered phone on file, inbound still acks as
  *Unmatched Caller*. Manual seed (below) remains valid for dev overrides.
- The async agent turn still routes **business tools** through the plugin's `INTEGRATION_DRIVER` (mock/composio), not `TOOL_BACKEND`. Case rows for inbound are opened at persist time so Workbench shows the thread immediately; agent `create_case` during the turn still uses mock unless you wire Composio + future composite driver work.
- A **live agent reply** needs a valid `OPENROUTER_API_KEY` (LLM) and, for outbound SMS, a working `SIMPLETEXTING_API_TOKEN` (the conversation_id is the contact's E.164 phone).
- With `TOOL_BACKEND` unset the production gateway does not boot at all: it fails
  closed rather than acking webhooks it can never reply to.

### Gateway + Workbench on the same Postgres

`pnpm dev` already puts the gateway, both dispatch servers, both workers and the
workbench on one Postgres with `TOOL_BACKEND=datastore` everywhere. Nothing to
wire.

For Shopify ingress phone match, set `COMPOSIO_TOOLKIT_VERSION_SHOPIFY=20260506_00`
(or newer) in `hermes-runtime/.env` so Composio exposes
`SHOPIFY_GET_CUSTOMERS_SEARCH`. The placeholder `00000000_00` toolkit only lists
customers and cannot search by phone.

Send an inbound (simulator or a real webhook) and a new case with the inbound
preview appears in the Workbench copilot queue, alongside the `0005_dev_bootstrap`
demo cases.

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

## Tests

```powershell
cd hermes-runtime
uv run pytest tests/test_gateway_app.py tests/test_gateway_composition.py tests/test_gateway_healthz.py -q
```

Webhook **token** verification unit tests live under `hermes/tests/test_gateway_verify.py`
(constant-time token compare, fail-closed — there is no signature crypto to test).
