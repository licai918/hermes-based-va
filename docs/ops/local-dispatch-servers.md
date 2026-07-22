# Local per-profile Hermes tool-dispatch servers

The workbench BFF reads structured resources by POSTing a `{ tool, action, params }`
envelope to a per-profile Hermes API over HTTP (`POST /v1/tools:dispatch`, ADR-0141).
Each Hermes profile runs as **its own process** with its own bearer token and port.
Per ADR-0142 these run **locally first**; Cloud Run packaging is the deferred cloud
target (Slice 37 / #40). This runbook brings up both servers and wires the BFF to
them. (Slice 34 / #37.)

## What runs

| Profile | Default port | Bearer (`DISPATCH_API_TOKEN`) | BFF routes |
| --- | --- | --- | --- |
| `internal_copilot` | 8081 | e.g. `dev-copilot-token` | `/api/copilot/*` |
| `supervisor_admin` | 8082 | e.g. `dev-admin-token` | `/api/admin/*` |

Each server boots from `hermes_runtime.tool_dispatch_composition:build_tool_dispatch_app`,
which **fails closed** (ADR-0095 pattern): a missing/unknown `TOEE_HERMES_PROFILE`
or a missing `DISPATCH_API_TOKEN` raises at boot rather than serving an
unauthenticated or wrong-profile dispatch route. The Profile Tool Allowlist
(ADR-0034/0035/0038) is enforced as a Tool Gate, so a tool outside the profile
returns a governed `policy_blocked` (HTTP 200), never a crash.

## Run both servers

Use the helper script (one per terminal), or the raw `uv` command it wraps.

PowerShell (Windows — uses Windows PowerShell or `pwsh`):

```powershell
# Terminal 1 — Internal Copilot Profile
powershell -ExecutionPolicy Bypass -File scripts/run-dispatch-server.ps1 `
    -Profile internal_copilot -Port 8081 -Token dev-copilot-token

# Terminal 2 — Supervisor Admin Profile
powershell -ExecutionPolicy Bypass -File scripts/run-dispatch-server.ps1 `
    -Profile supervisor_admin -Port 8082 -Token dev-admin-token
```

Cross-platform (run in `hermes-runtime/`):

```bash
# Terminal 1 — Internal Copilot Profile
TOEE_HERMES_PROFILE=internal_copilot DISPATCH_API_TOKEN=dev-copilot-token \
  uv run uvicorn hermes_runtime.tool_dispatch_composition:build_tool_dispatch_app \
  --factory --host 127.0.0.1 --port 8081

# Terminal 2 — Supervisor Admin Profile
TOEE_HERMES_PROFILE=supervisor_admin DISPATCH_API_TOKEN=dev-admin-token \
  uv run uvicorn hermes_runtime.tool_dispatch_composition:build_tool_dispatch_app \
  --factory --host 127.0.0.1 --port 8082
```

Each prints `Application startup complete` when ready.

## Back the tools with Postgres (optional)

The servers are **mock-first** (ADR-0137): unset `TOOL_BACKEND` dispatches against
the in-memory mock, so they run with no database. To hit the real system-of-record
(ADR-0140), bring up Postgres (see `local-datastore.md`) and add `-ToolBackend
datastore` (script) or `TOOL_BACKEND=datastore` (raw). `DATABASE_URL` defaults to the
docker-compose DSN. This axis is independent of `INTEGRATION_DRIVER` (external
vendors).

## Wire the workbench BFF

Point the BFF at the two servers via `apps/workbench/.env.local` (each
`*_API_TOKEN` must equal the matching server's `DISPATCH_API_TOKEN`):

```bash
HERMES_COPILOT_API_URL=http://127.0.0.1:8081
HERMES_COPILOT_API_TOKEN=dev-copilot-token
HERMES_ADMIN_API_URL=http://127.0.0.1:8082
HERMES_ADMIN_API_TOKEN=dev-admin-token
```

All four are REQUIRED (0.0.4 S09): the workbench is API-only, so it refuses to boot
without them and names whichever are missing -- there is no in-memory store left to
run on. `/api/copilot/*` reaches the copilot server and `/api/admin/*` the admin
server (route-derived profile, ADR-0093). Start the workbench with
`pnpm dev:workbench`.

## Verify

```bash
# Liveness (no auth)
curl http://127.0.0.1:8081/healthz            # -> {"status":"ok"}

# Missing/!wrong bearer -> 401
curl -i -X POST http://127.0.0.1:8081/v1/tools:dispatch \
  -H 'content-type: application/json' \
  -d '{"tool":"toee_workbench_read","action":"list_cases"}'   # -> HTTP/1.1 401

# Allowlisted read -> governed ok
curl -X POST http://127.0.0.1:8081/v1/tools:dispatch \
  -H 'authorization: Bearer dev-copilot-token' -H 'content-type: application/json' \
  -d '{"tool":"toee_workbench_read","action":"list_cases"}'   # -> {"ok":true,"data":{"cases":[]}}

# Tool outside the profile -> governed policy_blocked (HTTP 200)
curl -X POST http://127.0.0.1:8081/v1/tools:dispatch \
  -H 'authorization: Bearer dev-copilot-token' -H 'content-type: application/json' \
  -d '{"tool":"toee_workbench_admin","action":"list_accounts"}'
# -> {"ok":false,"error":{"class":"policy_blocked",...}}
```

On Windows PowerShell, use `Invoke-RestMethod` / `Invoke-WebRequest` instead of
`curl`.

## Tests

The composition root is covered without a database (mock-first):

```bash
uv run pytest tests/test_tool_dispatch_composition.py -v
```

These assert the fail-closed boot (missing/unknown profile, missing token) and the
served contract (`/healthz` 200, bearer 401, the profile's allowlist allow + a
cross-profile `policy_blocked`).

## Cloud (deferred)

Packaging each per-profile server as a Cloud Run service (Dockerfile, Secret Manager
tokens, service URLs) is Slice 37 (#40), gated on this local path being green
(ADR-0142). The app factory is already the `uvicorn --factory` entrypoint a container
`CMD` will use, so no rewrite is expected.
