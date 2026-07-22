# Local per-profile Hermes tool-dispatch servers

The workbench BFF reads structured resources by POSTing a `{ tool, action, params }`
envelope to a per-profile Hermes API over HTTP (`POST /v1/tools:dispatch`, ADR-0141).
Each Hermes profile runs as **its own process** with its own bearer token and port.
Per ADR-0142 these run **locally first**; Cloud Run packaging is the deferred cloud
target (Slice 37 / #40). This runbook brings up both servers and wires the BFF to
them. (Slice 34 / #37.)

## What runs

| Profile | Port | Bearer (`DISPATCH_API_TOKEN`) | BFF routes |
| --- | --- | --- | --- |
| `internal_copilot` | **8091** | `HERMES_COPILOT_API_TOKEN` | `/api/copilot/*` |
| `supervisor_admin` | **8092** | `HERMES_ADMIN_API_TOKEN` | `/api/admin/*`, `/api/auth/login` |

Each server boots from `hermes_runtime.tool_dispatch_composition:build_tool_dispatch_app`,
which **fails closed** (ADR-0095 pattern): a missing/unknown `TOEE_HERMES_PROFILE`
or a missing `DISPATCH_API_TOKEN` raises at boot rather than serving an
unauthenticated or wrong-profile dispatch route. The Profile Tool Allowlist
(ADR-0034/0035/0038) is enforced as a Tool Gate, so a tool outside the profile
returns a governed `policy_blocked` (HTTP 200), never a crash.

## Run both servers

```bash
pnpm dev
```

Both servers are `docker compose` services (`dispatch-copilot`, `dispatch-admin`)
as of 0.0.4 S10, and `pnpm dev` starts them with the rest of the stack and waits
for each `/healthz`. There is no hand-start step and no separate terminal any
more — see [`apps/workbench/README.md`](../../apps/workbench/README.md).

> **Running one by hand from a pre-S10 session?** Stop it. Ports 8081/8082 (the
> old hand-start convention) are not what the BFF talks to any more, and a
> process started weeks ago is serving weeks-old code — a pre-S05 admin server,
> for instance, answers `/admin/dead-letter` with `Unknown tool
> "toee_job_queue"`, which looks like an app bug and is not one. See
> [Stale hand-started servers](../../apps/workbench/README.md#stale-hand-started-servers).

`scripts/run-dispatch-server.ps1` still exists for the rare case of debugging one
server against host-side code, and takes `-Profile`, `-Port`, `-Token`,
`-ToolBackend`. Stop the composed service first (`docker compose stop
dispatch-copilot`) so the port is free.

## Backend axes

`pnpm dev` pins `TOOL_BACKEND=datastore` on both servers, so they dispatch against
the real system-of-record (ADR-0140). The servers are still **mock-first**
(ADR-0137) in code: unset `TOOL_BACKEND` dispatches against the in-memory mock and
needs no database, which is what the DB-free tests use. This axis is independent
of `INTEGRATION_DRIVER` (external vendors).

## How the BFF is wired

`apps/workbench/.env.local` is the source of truth, and `pnpm dev` reads the
tokens out of it and passes them to compose as each server's `DISPATCH_API_TOKEN`
— so the pair cannot drift:

```bash
HERMES_COPILOT_API_URL=http://127.0.0.1:8091
HERMES_COPILOT_API_TOKEN=dev-copilot-token
HERMES_ADMIN_API_URL=http://127.0.0.1:8092
HERMES_ADMIN_API_TOKEN=dev-admin-token
```

All four are REQUIRED (0.0.4 S09): the workbench is API-only, so it refuses to boot
without them and names whichever are missing -- there is no in-memory store left to
run on. `/api/copilot/*` reaches the copilot server and `/api/admin/*` the admin
server (route-derived profile, ADR-0093).

## Verify

```bash
# Liveness (no auth)
curl http://127.0.0.1:8091/healthz            # -> {"status":"ok"}

# Missing/!wrong bearer -> 401
curl -i -X POST http://127.0.0.1:8091/v1/tools:dispatch \
  -H 'content-type: application/json' \
  -d '{"tool":"toee_workbench_read","action":"list_cases"}'   # -> HTTP/1.1 401

# Allowlisted read -> governed ok
curl -X POST http://127.0.0.1:8091/v1/tools:dispatch \
  -H 'authorization: Bearer dev-copilot-token' -H 'content-type: application/json' \
  -d '{"tool":"toee_workbench_read","action":"list_cases"}'   # -> {"ok":true,"data":{"cases":[...]}}

# Tool outside the profile -> governed policy_blocked (HTTP 200)
curl -X POST http://127.0.0.1:8091/v1/tools:dispatch \
  -H 'authorization: Bearer dev-copilot-token' -H 'content-type: application/json' \
  -d '{"tool":"toee_workbench_admin","action":"list_accounts"}'
# -> {"ok":false,"error":{"class":"policy_blocked",...}}

# The admin server, on the queue tool S05 added (this is the one a stale
# hand-started server 500s on with `Unknown tool "toee_job_queue"`):
curl -X POST http://127.0.0.1:8092/v1/tools:dispatch \
  -H 'authorization: Bearer dev-admin-token' -H 'content-type: application/json' \
  -d '{"tool":"toee_job_queue","action":"list_dead_letters","params":{}}'
# -> {"ok":true,"data":{"jobs":[],"outbound":[],"recent_replays":[]}}
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
