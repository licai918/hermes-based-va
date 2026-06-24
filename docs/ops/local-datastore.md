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

## Tests

The datastore integration tests isolate themselves in a throwaway schema and
**skip** when no Postgres is reachable (so the suite stays green without a DB):

```bash
uv run pytest tests/test_datastore_migrate.py -v
```

With the container up they run for real and assert every system-of-record table
(ADR-0140) and the retention timestamp columns (ADR-0004/0116) exist.

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
