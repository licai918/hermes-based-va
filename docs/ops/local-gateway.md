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

After a **200 enqueue**, `LocalDispatchingJobQueue` runs the agent turn on a **background
thread** (fast-ack, ADR-0103). You do **not** need to call `/internal/jobs/agent-turn`
manually in local mode — that route exists for Cloud Tasks parity (ADR-0106).

---

## What store is used today

`build_gateway_app` wires **`InMemoryGatewayStore`** and **`LocalDispatchingJobQueue`**
(ADR-0105 local substrate, ADR-0140). Accepted inbound context lives **only in process memory**.

**Honest limits:**

- Inbound SMS simulation **does not** appear in the Workbench Postgres copilot queue
  (`pnpm dev:workbench` Tier B). There is no shared datastore between gateway and Workbench yet.
- Restarting the gateway **drops** in-memory context.
- A **live agent reply** needs a valid `OPENROUTER_API_KEY` (LLM) and, for outbound SMS,
  a working `TEXTLINE_ACCESS_TOKEN` + real or sandbox `conversation_id`. Signature-only webhook
  smoke succeeds without a model call; the async turn may log errors if tokens are fake.
- Durable Postgres + Cloud Tasks replace the in-memory store/queue in a later slice (#40).

---

## Tests

```powershell
cd hermes-runtime
uv run pytest tests/test_gateway_app.py tests/test_gateway_composition.py tests/test_gateway_healthz.py -q
```

Signature crypto unit tests live under `hermes/tests/test_gateway_verify.py`.
