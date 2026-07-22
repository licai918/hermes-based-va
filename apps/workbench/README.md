# Toee Workbench

The internal Next.js app (App Router) plus its BFF. The BFF holds **no business
logic and no store**: every resource read and every governed write is a
`{ tool, action, params }` envelope POSTed to a per-profile Hermes tool-dispatch
server over HTTP (ADR-0141). `/api/copilot/*` goes to the `internal_copilot`
server, `/api/admin/*` and login go to the `supervisor_admin` server.

Since 0.0.4 S09 there is **no in-memory fallback**. The app fails closed at boot
if `HERMES_COPILOT_API_URL/TOKEN` or `HERMES_ADMIN_API_URL/TOKEN` are missing —
it names the missing variables and exits. So running the workbench means running
the stack. That is what the one command below is for.

---

## Run it

From the **repo root**:

```bash
pnpm dev
```

That is the whole local dev path. It is safe to run every day — migrations are
idempotent and it never wipes your database.

Then log in at <http://localhost:3000/login>:

| Username | Role | Password |
| --- | --- | --- |
| `rep` | Customer service rep | `Workbench123!` |
| `supervisor` | Workbench supervisor | `Workbench123!` |
| `admin` | Workbench admin | `Workbench123!` |

Ctrl-C stops the workbench dev server; the containers keep running. Stop those
with `docker compose down` (add `-v` only if you mean to destroy your local data).

### What `pnpm dev` starts

`scripts/dev-up.mjs` runs four phases and **waits for a real readiness signal at
each one** — not just for `docker compose` to return.

| Phase | Service | Where | Port | Ready when |
| --- | --- | --- | --- | --- |
| 1 | Postgres (`toee_va` + `toee_knowledge`) | container | 5432 | `pg_isready` healthcheck passes |
| 2 | migrations + dev seed | one-shot container | — | both migrate modules exit 0 |
| 3 | `internal_copilot` dispatch | container | **8091** | `GET /healthz` answers 200 |
| 3 | `supervisor_admin` dispatch | container | **8092** | `GET /healthz` answers 200 |
| 3 | gateway (inbound SMS) | container | **8080** | `GET /healthz` answers 200 |
| 3 | `turn_worker` | container | — | container state is `running` |
| 3 | `background_worker` | container | — | container state is `running` |
| 4 | workbench dev server | **host** | 3000 | `GET /login` answers |

The workbench runs on the host (its `node_modules` and hot reload already live
there); everything else runs in `docker compose`, which is also where the
healthchecks live.

Both workers matter. `turn_worker` is the only thing that runs an inbound agent
turn (the gateway just enqueues), and `background_worker` is the only thing that
runs the schedule tick, the retention sweep, the L6 review fork and re-ingest.

```bash
pnpm dev:stack   # same stack, no workbench dev server (CI / running the UI yourself)
```

### Prerequisites

| Tool | Purpose |
| --- | --- |
| Docker Desktop | Postgres + every Python service |
| pnpm | this app and the monorepo scripts |
| Node ≥ 20 | `scripts/dev-up.mjs` |

`uv` is **not** required for `pnpm dev` — the Python services run from the
container image. You still want it to run `pytest` locally.

First run builds the `toee-hermes-runtime:local` image (a `uv sync` over the
pinned lock — several minutes, once). Every `pnpm dev` after that rebuilds it
again via phase 2's `docker compose run --rm --build migrate`, so a Python
code or dependency change is picked up on the very next run — no manual
`docker compose build` needed.

---

## Configuration

Two gitignored files. `pnpm dev` reads both and passes the values through to
compose, so the workbench's bearer and the dispatch server's `DISPATCH_API_TOKEN`
cannot drift apart.

### `apps/workbench/.env.local` — written for you if absent

Source of truth for anything the workbench and a server must agree on.

| Variable | Required | Notes |
| --- | --- | --- |
| `HERMES_COPILOT_API_URL` | yes | `http://127.0.0.1:8091` |
| `HERMES_COPILOT_API_TOKEN` | yes | becomes the copilot server's `DISPATCH_API_TOKEN` |
| `HERMES_ADMIN_API_URL` | yes | `http://127.0.0.1:8092` |
| `HERMES_ADMIN_API_TOKEN` | yes | becomes the admin server's `DISPATCH_API_TOKEN` |
| `WORKBENCH_SESSION_SECRET` | no | session cookie signing; a dev fallback applies when unset |
| `SIMULATOR_GATEWAY_URL` | for the simulator | `http://127.0.0.1:8080` |
| `TEXTLINE_WEBHOOK_SECRET` | for the simulator | dev default here, but `hermes-runtime/.env` wins if it also sets this (needed to match a real provider); a mismatch is a 401 on every simulated inbound |

### `hermes-runtime/.env` — real credentials

Mounted into every Python container. `pnpm dev` also reads `INTERNAL_JOB_SECRET`
and `REPLY_SENDER` out of it so its own dev defaults never clobber your values.

| Variable | Effect if unset |
| --- | --- |
| `OPENROUTER_API_KEY` | copilot chat and the inbound agent turn have no live model (0.0.4 S09 deleted the TS stub) |
| `INTERNAL_JOB_SECRET` | dev default is used |
| `REPLY_SENDER` | defaults to `simulated`: no real SMS leaves a dev box, and the reply still mirrors into `message_turn` so the simulator can read it |
| `INGEST_CORPUS_PATH` | a queued `ingest` job dead-letters immediately, naming this variable |
| `AGENT_EXPERIENCE_LEARNING` + `OPENROUTER_API_KEY` | an `l6_review` job fails loudly by design (`L6ReviewMisconfigured`) |

`TOOL_BACKEND=datastore` is **not** yours to set — compose pins it on the
gateway and both workers, which fail closed without it.

---

## Stale hand-started servers

Before S10 the runbooks told you to start the dispatch servers by hand, in their
own terminals, on **8081/8082**. Those instructions are gone. If you have such a
process left over from an earlier session, it is running whatever code was
checked out then — a pre-S05 admin server, for example, 500s on
`/admin/dead-letter` with `Unknown tool "toee_job_queue"`, which reads as an
application bug and is not one.

The composed servers use **8091/8092**, so a leftover on 8081/8082 does not
collide — it just sits there answering nothing. A leftover on 8091/8092 *does*
collide, and `pnpm dev` fails with `port is already allocated` plus a pointer
back here.

Find and stop them:

```powershell
# Windows PowerShell — what owns the port
Get-NetTCPConnection -State Listen -LocalPort 8080,8081,8082,8091,8092 |
  Select-Object LocalPort, OwningProcess
Stop-Process -Id <pid>
```

```bash
# Git Bash / macOS / Linux
npx kill-port 8080 8081 8082 8091 8092
```

Closing the terminal that started them works too. Nothing in this repo needs a
hand-started server any more.

---

## Verify the stack

```bash
curl http://127.0.0.1:8091/healthz    # {"status":"ok"}
curl http://127.0.0.1:8092/healthz    # {"status":"ok"}
curl http://127.0.0.1:8080/healthz    # {"status":"ok"}
docker compose ps                      # postgres healthy; both workers running
```

Then in the browser: log in as `rep`, confirm `case_ar_urgent` and
`case_toolfail` in the copilot queue (seeded by migration `0005_dev_bootstrap`),
open one, claim it, draft an SMS.

The **External Profile Simulator** exercises the full inbound path — workbench →
signed webhook → gateway → `job` row → `turn_worker` → reply mirrored into
`message_turn`. It needs the gateway *and* `turn_worker`, which `pnpm dev` gives
you. Details: [`docs/ops/local-gateway.md`](../../docs/ops/local-gateway.md).

## Tests

```bash
cd apps/workbench
npx vitest run
npx tsc --noEmit
```

The BFF suite mocks the HTTP client seam and needs no running stack.

```bash
node scripts/dev-up.mjs --selfcheck   # env-file parsing in the dev-up script
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Docker is not reachable` | Start Docker Desktop. The script already ignores a stale `DOCKER_HOST=tcp://localhost:2375`. |
| `port is already allocated` | A hand-started server or another Postgres owns it — see above. |
| Workbench exits with `Hermes API configuration missing: ...` | Expected fail-closed boot (S09). Delete `apps/workbench/.env.local` and re-run `pnpm dev` to regenerate it. |
| Dispatch **401** | `HERMES_*_API_TOKEN` changed without a restart — re-run `pnpm dev` so compose picks the new value up. |
| Empty copilot queue | The dev seed is applied by phase 2 with `HERMES_APPLY_DEV_SEED=1`; check `docker compose logs migrate`. |
| Locked out after 5 bad passwords | The 15-minute lockout ladder lives in Postgres (ADR-0018) and survives restarts. Clear it: `docker exec toee-va-postgres psql -U toee -d toee_va -c "UPDATE workbench_account SET failed_attempts = 0, locked_until = NULL WHERE username = 'rep';"` |
| `turn-worker` is not running | It fails closed without `TOOL_BACKEND=datastore`; read `docker compose logs turn-worker`. |

## Further reading

- [`docs/ops/local-e2e.md`](../../docs/ops/local-e2e.md) — verification checklist, seed data
- [`docs/ops/local-dispatch-servers.md`](../../docs/ops/local-dispatch-servers.md) — what each profile server serves
- [`docs/ops/local-gateway.md`](../../docs/ops/local-gateway.md) — inbound SMS, workers, webhook signing
- [`docs/ops/local-datastore.md`](../../docs/ops/local-datastore.md) — schema and migrations
