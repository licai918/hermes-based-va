# Local-first datastore and per-profile API servers; cloud deploy deferred

## Context

ADR-0140 makes the **Toee Business Datastore (Postgres)** the system-of-record,
described as "activated on demand (Cloud SQL on Cloud Run)." ADR-0141 deploys the
two per-profile Hermes backends (deterministic `tools:dispatch` + agent-turn) "as
separate Cloud Run services." Both frame a managed cloud as the substrate, and the
ADR-0141 tracer-bullet deliberately ran against `MockDriver` because no database or
runnable per-profile service exists yet.

The build sequence the team wants is **local-first**: every component that needs a
database or a long-running server is stood up and proven end-to-end locally before
any managed cloud resource is provisioned. This keeps onboarding fast (the
mock-first spirit of ADR-0137), avoids premature cloud spend (demand-driven
ADR-0025), and lets the HTTP seams, schema, and migrations be validated without
GCP credentials.

## Decision

Build and prove locally first; make cloud provisioning a later, separate slice
gated on the local path being green.

- **Datastore (ADR-0140).** A **local Postgres** (docker-compose, repo-local
  connection config) is the dev system-of-record substrate. Schema and migrations
  are authored against local Postgres; the same migrations target Cloud SQL later.
  Cloud SQL is deferred.
- **Per-profile Hermes backends (ADR-0141).** The `internal_copilot` and
  `supervisor_admin` `tools:dispatch` + agent-turn services run as **local
  processes** — one `HERMES_HOME` each, one bearer token each — reachable by the
  workbench BFF over `http://localhost:<port>`. Per-profile Cloud Run services are
  deferred.
- **Secrets/config.** Local `.env` + dev bearer tokens for development. GCP Secret
  Manager and OIDC (ADR-0098) move into the deferred cloud slice.
- **Cloud cutover is its own slice.** Containerize the per-profile API servers,
  provision Cloud SQL, wire Secret Manager + OIDC, and extend
  `docs/ops/deploy-cloud-run.md` — only after the local end-to-end path is green.

This **refines, not reverses** ADR-0140/0141/0098/0025: the target architecture
still includes Cloud SQL and Cloud Run; local-first only sequences *when* each
lands. Where those ADRs read "Cloud SQL" / "Cloud Run service," read "local
Postgres" / "local process" for the development phase, with the cloud form as the
deferred target.

## Considered options

- **Local-first, cloud-deferred (chosen).** Fast onboarding, no premature spend,
  seams + schema + migrations validated without credentials; consistent with
  mock-first (ADR-0137) and demand-driven (ADR-0025).
- **Cloud-from-day-one (rejected).** Requires a GCP project, Cloud SQL, Secret
  Manager, and OIDC before any end-to-end test; slow, costly, credential-gated;
  contradicts ADR-0025.
- **Stay on MockDriver until the cloud slice (rejected).** Never exercises real
  SQL, migrations, retention, or transactional behavior before production; defers
  all datastore risk to the riskiest moment.

## Verification

This ADR is design + sequencing only. It is realized by the local-first slices:
local Postgres schema/migrations, Postgres-backed tool handlers, runnable
per-profile API servers, full BFF→HTTP resource cutover, and the copilot
chat/drafts agent-turn path — each green locally before a final cloud-deploy slice
(per-profile Cloud Run services + Cloud SQL + Secret Manager).
