# Local Toee Business Datastore (Postgres)

The Toee Business Datastore is the system-of-record (ADR-0140). Per ADR-0142 it
runs as **local Postgres first**; Cloud SQL is the deferred cloud target. This
runbook brings it up locally and applies the schema. (Slice 32 / #35.)

## Bring up Postgres

From the repo root:

```bash
docker compose up -d postgres
```

This starts `postgres:16` (service `postgres`, container `toee-va-postgres`) on
`localhost:5432` with user/password/db = `toee` / `toee` / `toee_va`, backed by the
named volume `toee_pgdata`. Wait until healthy:

```bash
docker inspect -f '{{.State.Health.Status}}' toee-va-postgres
```

## Apply migrations

Migrations are plain SQL in `hermes-runtime/migrations/`, applied in lexical order
and tracked in a `schema_migrations` table (idempotent). Run from `hermes-runtime/`:

```bash
uv run python -m hermes_runtime.datastore.migrate
```

First run prints `applied migrations: 0001_initial_schema`; a re-run prints
`no pending migrations`. Connection comes from `DATABASE_URL` (see `.env.example`),
defaulting to the docker-compose DSN above — no GCP credentials needed locally.

The `0005_dev_bootstrap` seed (demo accounts + cases) is LOCAL DEV ONLY and is
skipped unless you set `HERMES_APPLY_DEV_SEED=1`, so a cloud/prod migrate never
seeds demo data (ADR-0142). Tier B walkthrough: [`local-e2e.md`](local-e2e.md).

## Datastore-backed tools (Slice 33 / #36)

The `PostgresDriver` (`hermes_runtime/datastore/`) runs real SQL behind the
internal **system-of-record** tools, replacing the in-memory mock for those tools.
It is selected on a separate axis from `INTEGRATION_DRIVER` (the external-vendor
backend): set `TOOL_BACKEND=datastore` to back these tools with Postgres, or leave
it unset for the mock-first default (ADR-0137):

- `toee_case`, `toee_case_manage`, `toee_workbench_read` — cases + audit log
- `toee_customer_memory` — preference slots (ADR-0110–0114)
- `toee_identity_lookup` — channel↔Shopify identity links (read-only)
- `toee_workbench_admin` — accounts (ADR-0069/0089)
- `toee_knowledge_ops` — policy-slot versions (ADR-0003/0040)
- `toee_eval_review` — eval runs + policy promotion (ADR-0074/0040)

External-vendor tools (Shopify, QBO, EasyRoutes, Square, SimpleTexting) and LLM drafts
stay on the mock/Composio path — they are not system-of-record. The driver runs
behind the **same** governed `execute_tool` as the mock (catalog check → Tool Gate
→ profile allowlist all run first), and every mutation writes a Workbench Audit Log
row in the same transaction (ADR-0029/0085), so swapping the backend introduces no
governance drift. A no-drift test pins the datastore registry to both the v1 tool
catalog and the mock registry.

## Tests

The datastore integration tests isolate themselves in a throwaway schema and
**skip** when no Postgres is reachable (so the suite stays green without a DB):

```bash
uv run pytest tests/test_datastore_migrate.py tests/test_datastore_driver_*.py -v
```

With the container up they run for real: the migrate test asserts every
system-of-record table (ADR-0140) and retention timestamp column (ADR-0004/0116)
exists, and the `test_datastore_driver_*` tests exercise the `PostgresDriver` CRUD
and audit writes end-to-end against a throwaway schema. The backend-selection and
no-drift tests need no database:

```bash
uv run pytest tests/test_tool_backend.py -v
```

## Teardown

```bash
docker compose down            # stop, keep data
docker compose down -v         # stop and delete the toee_pgdata volume
```

## Troubleshooting

- **`error during connect ... //./pipe/dockerDesktopLinuxEngine ... cannot find the file`** —
  Docker Desktop's engine is not running. Start Docker Desktop and wait for the
  whale icon to settle.
- **`dial tcp [::1]:2375 ... actively refused`** — a stale `DOCKER_HOST` env var
  is overriding the active context. Unset it (`Remove-Item Env:DOCKER_HOST` in
  PowerShell) or select the Docker Desktop context
  (`$env:DOCKER_CONTEXT='desktop-linux'`).
- **Port 5432 already in use** — another Postgres is running locally; stop it or
  remap the host port in `docker-compose.yml`.

## Cloud (deferred)

Cloud SQL provisioning, Secret Manager DB credentials, and applying these same
migrations in the cloud are Slice 37 (#40), gated on the local path being green
(ADR-0142). The migration SQL is plain and Cloud SQL-portable, so no rewrite is
expected.
