# Local end-to-end runbook

The one command, what it brings up, and how to check it worked.

> **There is no in-memory tier any more.** 0.0.4 S09 deleted the workbench's
> in-memory stores, so Postgres + both dispatch servers are the only way to run the
> app. The BFF refuses to boot without `HERMES_COPILOT_API_URL/TOKEN` and
> `HERMES_ADMIN_API_URL/TOKEN` — it names the missing variables and exits rather
> than starting on a fake backend. (The old "Tier A" quick demo is gone; what this
> file used to call "Tier B" is now just "local".)
>
> **The four-terminal hand-start is gone too** (0.0.4 S10). If you still have
> dispatch servers running from a pre-S10 session, stop them — see
> [Stale hand-started servers](../../apps/workbench/README.md#stale-hand-started-servers).

See also: [`apps/workbench/README.md`](../../apps/workbench/README.md) (the dev
path itself), [`local-datastore.md`](local-datastore.md),
[`local-dispatch-servers.md`](local-dispatch-servers.md), repo-root
[`.env.example`](../../.env.example).

## Prerequisites

| Tool | Purpose |
| --- | --- |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Postgres + every Python service |
| [pnpm](https://pnpm.io/) | Workbench + monorepo scripts |
| Node ≥ 20 | `scripts/dev-up.mjs` |
| [uv](https://docs.astral.sh/uv/) | *only* for running `pytest` / Python tooling on the host |

From the repo root once:

```bash
pnpm install
```

---

## The local path

```bash
pnpm dev
```

`scripts/dev-up.mjs` brings up Postgres (+ the separate `toee_knowledge`
database), applies every migration with the dev seed, starts both dispatch
servers, the gateway and both workers in `docker compose`, then starts the
workbench dev server on the host — waiting for a real readiness signal at each
step (`pg_isready`, then `/healthz` per server).

| Service | Where | Port |
| --- | --- | --- |
| Postgres (`toee_va`, `toee_knowledge`) | container | 5432 |
| `internal_copilot` dispatch | container | 8091 |
| `supervisor_admin` dispatch | container | 8092 |
| Gateway (inbound SMS) | container | 8080 |
| `turn_worker`, `background_worker` | containers | — |
| Workbench dev server | host | 3000 |

Open [http://localhost:3000](http://localhost:3000). Ctrl-C stops the workbench;
`docker compose down` stops the containers.

`pnpm dev:stack` does the same without the workbench dev server.

The full option table (env files, prerequisites, troubleshooting) lives in
[`apps/workbench/README.md`](../../apps/workbench/README.md); it is not repeated
here.

Schema detail: [`local-datastore.md`](local-datastore.md). The dev bootstrap
accounts + demo cases are LOCAL DEV ONLY and are opted in by `pnpm dev` setting
`HERMES_APPLY_DEV_SEED=1` on the migrate step — a cloud/prod migrate omits it and
never seeds demo data.

---

## Post-seed login credentials

Migration `0005_dev_bootstrap` seeds three accounts. **Password for all:**
`Workbench123!`

| Username | Role | Account ID | Typical use |
| --- | --- | --- | --- |
| `rep` | Customer service rep | `seed-rep` | Copilot queue, case actions, SMS draft/send |
| `supervisor` | Workbench supervisor | `seed-supervisor` | Supervisor routes (same password) |
| `admin` | Workbench admin | `seed-admin` | `/admin` accounts, knowledge slots, eval |

These accounts live in Postgres (`workbench_account`); the workbench verifies
credentials through `toee_workbench_admin.authenticate`, never in-process.

**Locked yourself out?** Five wrong passwords in a row lock an account for 15
minutes (ADR-0018). That ladder lives in Postgres, so it survives restarting the
dispatch server or the workbench — restarting is not the way out. Clear it:

```bash
docker exec toee-va-postgres psql -U toee -d toee_va \
  -c "UPDATE workbench_account SET failed_attempts = 0, locked_until = NULL WHERE username = 'rep';"
```

Demo cases seeded for the copilot queue:

| Case ID | Notes |
| --- | --- |
| `case_ar_urgent` | Urgent SMS, active session — good for queue + Textline send after claim |
| `case_toolfail` | Urgent billing, `tool_failure` flag |

Thread previews and identity summaries follow migration `0005_dev_bootstrap`.

---

## Verification checklist

Run these once `pnpm dev` has printed its login banner.

### 1. Dispatch + gateway health

```bash
curl http://127.0.0.1:8091/healthz   # -> {"status":"ok"}   internal_copilot
curl http://127.0.0.1:8092/healthz   # -> {"status":"ok"}   supervisor_admin
curl http://127.0.0.1:8080/healthz   # -> {"status":"ok"}   gateway
docker compose ps                     # both workers `running`
```

`pnpm dev` already polls all three; this is for checking a stack you left up.

### 2. Login

1. Open [http://localhost:3000/login](http://localhost:3000/login).
2. Sign in as `rep` / `Workbench123!`.
3. Confirm redirect to the copilot queue.

### 3. Knowledge slots (admin)

1. Log in as `admin` (or use an admin session).
2. Open **Admin — Knowledge**.
3. Confirm six policy slots (empty placeholders from migration `0003_knowledge_slots`).

### 4. Case queue (copilot)

1. Log in as `rep`.
2. Open the copilot queue.
3. Confirm `case_ar_urgent` and `case_toolfail` appear (urgent tier first).

### 5. SMS draft

1. Open `case_ar_urgent`.
2. Claim the case.
3. Use **Draft SMS** — the reply is a real `internal_copilot` agent turn over
   `POST /v1/agent:turn`. Without `OPENROUTER_API_KEY` the dispatch server falls
   back to its own deterministic keyless completion, so the panel still works
   offline; the outbound send itself uses the mock Textline capture, so no live
   Textline token is required.

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
| `port is already allocated` (8080/8091/8092) | A hand-started server from a pre-S10 session still owns it — [stop it](../../apps/workbench/README.md#stale-hand-started-servers). |
| Port **5432** in use | Stop other Postgres or remap the host port in `docker-compose.yml`. |
| `error during connect ... dockerDesktopLinuxEngine` | Docker engine not running — start Docker Desktop. |
| `dial tcp [::1]:2375 ... refused` | Stale `DOCKER_HOST`. `pnpm dev` already ignores it; a raw `docker compose` call needs it unset (or `DOCKER_CONTEXT=desktop-linux`). |
| Workbench exits at startup with `Hermes API configuration missing: ...` | Expected fail-closed boot (0.0.4 S09). Delete `apps/workbench/.env.local` and re-run `pnpm dev` to regenerate it. |
| Login fails | `docker compose logs dispatch-admin`; the admin server is what authenticates. |
| Empty copilot queue | `docker compose logs migrate` — phase 2 applies `0005_dev_bootstrap` with `HERMES_APPLY_DEV_SEED=1`. |
| Dispatch **401** | Bearer mismatch — `HERMES_*_API_TOKEN` in `apps/workbench/.env.local` is the source of truth; re-run `pnpm dev` after editing so compose picks it up. |

More detail: [`local-datastore.md`](local-datastore.md) (Postgres), [`local-dispatch-servers.md`](local-dispatch-servers.md) (dispatch).

---

## Optional — not required locally

These are deferred or optional locally:

| Topic | Notes |
| --- | --- |
| **OpenRouter** | Drafts and copilot chat are real agent turns; a *live model* needs `OPENROUTER_API_KEY` in `hermes-runtime/.env`, which compose mounts into the dispatch servers. Without it the Python runtime uses its deterministic keyless completion, so the panels still work — the replies are just canned. (The TypeScript stub is gone as of 0.0.4 S09.) Automated tests drive the turn through `scripted_completions` instead. |
| **Live outbound SMS** | `pnpm dev` sets `REPLY_SENDER=simulated`, so a dev box never posts to the real provider; the reply still mirrors into `message_turn`. Set `REPLY_SENDER=textline` + a token in `hermes-runtime/.env` only if you mean it. |
| **Gateway** | Already up on :8080 as part of `pnpm dev`. Webhook signing and the inbound path: [`local-gateway.md`](local-gateway.md). |

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
