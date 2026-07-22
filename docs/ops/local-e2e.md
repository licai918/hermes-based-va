# Local end-to-end runbook (Tier A + Tier B)

This runbook chains the local-first paths (ADR-0142) so a new developer can reach a
working Workbench in about 30 minutes. **Tier B** is the full Postgres + dual
dispatch + Workbench API path �?the target of Increment 1. **Tier A** is the
fast in-memory demo when you only need UI smoke without Docker.

See also: [`local-datastore.md`](local-datastore.md), [`local-dispatch-servers.md`](local-dispatch-servers.md), repo-root [`.env.example`](../../.env.example).

## Prerequisites

| Tool | Purpose |
| --- | --- |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Local Postgres (`docker compose`) |
| [pnpm](https://pnpm.io/) | Workbench + monorepo scripts (`pnpm dev:workbench`) |
| [uv](https://docs.astral.sh/uv/) | Hermes runtime, migrations, dispatch servers |

From the repo root once:

```bash
pnpm install
cd hermes-runtime && uv sync
```

---

## Tier A �?in-memory quick demo (~5 min)

No Docker, no dispatch servers. The Workbench BFF uses in-memory stores (ADR-0137).

```bash
pnpm dev:workbench
```

Open [http://localhost:3000](http://localhost:3000). Log in with any seeded account
below (same passwords as Tier B). The copilot queue, knowledge slots, and drafts
render from `apps/workbench/lib/gateway/seed.ts`.

Use Tier A for UI-only work. For Postgres-backed API mode, continue to Tier B.

---

## Tier B �?full local API path (~30 min)

Four terminals after one-time setup. All commands assume repo root unless noted.

### Terminal 1 �?Postgres + schema

```bash
docker compose up -d postgres
```

Wait until healthy:

```bash
docker inspect -f '{{.State.Health.Status}}' toee-va-postgres
# -> healthy
```

Apply migrations. The dev bootstrap accounts + demo cases are LOCAL DEV ONLY and
must be **opted in** with `HERMES_APPLY_DEV_SEED=1` -- a plain migrate applies
schema only, so a cloud/prod migrate never seeds demo data:

```bash
cd hermes-runtime
HERMES_APPLY_DEV_SEED=1 uv run python -m hermes_runtime.datastore.migrate
```

First run prints `applied migrations: �? 0005_dev_bootstrap`. Re-runs print
`no pending migrations` (bootstrap inserts are idempotent).

Details: [`local-datastore.md`](local-datastore.md).

### Terminal 2 �?Internal Copilot dispatch (port 8081)

PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run-dispatch-server.ps1 `
    -Profile internal_copilot -Port 8081 -Token dev-copilot-token -ToolBackend datastore
```

Cross-platform (from `hermes-runtime/`):

```bash
TOEE_HERMES_PROFILE=internal_copilot DISPATCH_API_TOKEN=dev-copilot-token \
  TOOL_BACKEND=datastore \
  uv run uvicorn hermes_runtime.tool_dispatch_composition:build_tool_dispatch_app \
  --factory --host 127.0.0.1 --port 8081
```

### Terminal 3 �?Supervisor Admin dispatch (port 8082)

PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run-dispatch-server.ps1 `
    -Profile supervisor_admin -Port 8082 -Token dev-admin-token -ToolBackend datastore
```

Cross-platform (from `hermes-runtime/`):

```bash
TOEE_HERMES_PROFILE=supervisor_admin DISPATCH_API_TOKEN=dev-admin-token \
  TOOL_BACKEND=datastore \
  uv run uvicorn hermes_runtime.tool_dispatch_composition:build_tool_dispatch_app \
  --factory --host 127.0.0.1 --port 8082
```

Details: [`local-dispatch-servers.md`](local-dispatch-servers.md).

### Terminal 4 �?Workbench BFF

Create `apps/workbench/.env.local`:

```bash
# Session cookie signing (optional locally �?same value as the dev fallback in
# apps/workbench/lib/auth/session-secret.ts when unset).
WORKBENCH_SESSION_SECRET=workbench-dev-session-secret-change-me

# Per-profile Hermes dispatch servers (tokens must match DISPATCH_API_TOKEN above).
HERMES_COPILOT_API_URL=http://127.0.0.1:8081
HERMES_COPILOT_API_TOKEN=dev-copilot-token
HERMES_ADMIN_API_URL=http://127.0.0.1:8082
HERMES_ADMIN_API_TOKEN=dev-admin-token
```

Start the app:

```bash
pnpm dev:workbench
```

Open [http://localhost:3000](http://localhost:3000).

---

## Post-seed login credentials

Migration `0005_dev_bootstrap` seeds three accounts. **Password for all:**
`Workbench123!`

| Username | Role | Account ID | Typical use |
| --- | --- | --- | --- |
| `rep` | Customer service rep | `seed-rep` | Copilot queue, case actions, SMS draft/send |
| `supervisor` | Workbench supervisor | `seed-supervisor` | Supervisor routes (same password) |
| `admin` | Workbench admin | `seed-admin` | `/admin` accounts, knowledge slots, eval |

These mirror the in-memory `AccountStore` seed (`apps/workbench/lib/auth/account-store.ts`).

**Locked yourself out?** Five wrong passwords in a row lock an account for 15
minutes (ADR-0018). In Tier B that ladder lives in Postgres, so it survives
restarting the dispatch server or the workbench — restarting is not the way out.
Clear it:

```bash
docker exec toee-va-postgres psql -U toee -d toee_va \
  -c "UPDATE workbench_account SET failed_attempts = 0, locked_until = NULL WHERE username = 'rep';"
```

Demo cases seeded for the copilot queue:

| Case ID | Notes |
| --- | --- |
| `case_ar_urgent` | Urgent SMS, active session �?good for queue + Textline send after claim |
| `case_toolfail` | Urgent billing, `tool_failure` flag |

Thread previews and identity summaries follow `apps/workbench/lib/gateway/seed.ts`.

---

## Verification checklist

Run these after Tier B is up.

### 1. Dispatch health

```bash
curl http://127.0.0.1:8081/healthz   # -> {"status":"ok"}
curl http://127.0.0.1:8082/healthz   # -> {"status":"ok"}
```

### 2. Login

1. Open [http://localhost:3000/login](http://localhost:3000/login).
2. Sign in as `rep` / `Workbench123!`.
3. Confirm redirect to the copilot queue.

### 3. Knowledge slots (admin)

1. Log in as `admin` (or use an admin session).
2. Open **Admin �?Knowledge**.
3. Confirm six policy slots (empty placeholders from migration `0003_knowledge_slots`).

### 4. Case queue (copilot)

1. Log in as `rep`.
2. Open the copilot queue.
3. Confirm `case_ar_urgent` and `case_toolfail` appear (urgent tier first).

### 5. SMS draft

1. Open `case_ar_urgent`.
2. Claim the case.
3. Use **Draft SMS** �?should succeed (mock Textline path; no live Textline token required).

### 6. Audit row

1. After viewing a case or generating a draft, open the case audit log.
2. Confirm a new audit entry (or dispatch a read via admin/copilot API and query Postgres):

```bash
cd hermes-runtime
uv run python -c "
import psycopg
from hermes_runtime.datastore.config import database_url
with psycopg.connect(database_url()) as c:
    with c.cursor() as cur:
        cur.execute('SELECT action, target_id FROM workbench_audit_log ORDER BY created_at DESC LIMIT 5')
        for row in cur.fetchall(): print(row)
"
```

Governed writes append rows in the same transaction (ADR-0029/0085).

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Port **5432** in use | Stop other Postgres or remap the host port in `docker-compose.yml`. |
| Docker **not healthy** | Start Docker Desktop; `docker inspect -f '{{.State.Health.Status}}' toee-va-postgres` should be `healthy`. |
| `error during connect ... dockerDesktopLinuxEngine` | Docker engine not running �?start Docker Desktop. |
| `dial tcp [::1]:2375 ... refused` | Stale `DOCKER_HOST` �?unset it or set `DOCKER_CONTEXT=desktop-linux`. |
| Login works in Tier A but not Tier B | Confirm Terminal 3 (admin dispatch) is up with `TOOL_BACKEND=datastore` and `HERMES_ADMIN_API_*` is set in `.env.local`. |
| Empty copilot queue in Tier B | Re-run migrate **with `HERMES_APPLY_DEV_SEED=1`**; confirm `0005_dev_bootstrap` applied and copilot server uses `TOOL_BACKEND=datastore`. |
| Dispatch **401** | Bearer token mismatch �?`HERMES_*_API_TOKEN` must equal that server's `DISPATCH_API_TOKEN`. |

More detail: [`local-datastore.md`](local-datastore.md) (Postgres), [`local-dispatch-servers.md`](local-dispatch-servers.md) (dispatch).

---

## Optional �?not required for Tier B

These are deferred or optional for local Tier B:

| Topic | Notes |
| --- | --- |
| **#45 lockout** | API-path login does not yet enforce in-memory brute-force lockout (ADR-0144 M-2). Repeated bad passwords are not throttled when the admin API is configured. |
| **OpenRouter** | Agent-turn / LLM drafts against live models need `OPENROUTER_API_KEY` on the gateway path �?not required for queue, login, or mock Textline send. |
| **Live Textline** | Outbound SMS uses the mock Textline capture in local dev; `TEXTLINE_ACCESS_TOKEN` is for production/live integration. |
| **Gateway** | Inbound Textline webhook + async agent turn � see [`local-gateway.md`](local-gateway.md) (`pnpm dev:gateway` is a stub; use uvicorn). |

Cloud SQL, Cloud Run, and Secret Manager wiring remain Slice 37 (#40).

---

## Tests

```bash
cd hermes-runtime
uv run pytest tests/test_datastore_dev_bootstrap.py -v
```

With Postgres up, the suite also runs broader datastore integration tests:

```bash
uv run pytest tests/test_datastore_migrate.py tests/test_datastore_dev_bootstrap.py -v
```

Teardown: `docker compose down` (add `-v` to wipe the volume).
