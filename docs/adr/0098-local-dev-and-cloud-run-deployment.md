# Local development and Cloud Run deployment conventions

The monorepo uses local pnpm development by default and deploys `apps/workbench` and `services/hermes-gateway` as separate Cloud Run services.

## Local development

Day-to-day development runs without Docker:

- `pnpm dev:workbench` — Next.js workbench on port `3000`
- `pnpm dev:gateway` — Fastify gateway on port `8080`

`docker-compose` is optional and reserved for smoke tests or production-like local integration, not required for normal feature work.

## Environment variable layering

Environment configuration is split by service:

- root `.env.example` — documented variable catalog for the repo
- `apps/workbench/.env.local` — workbench-only secrets and config such as session secrets
- `services/hermes-gateway/.env.local` — gateway-only secrets and config such as Textline credentials

Shared secrets such as model-provider keys may be documented in the root example file but should still be supplied per service only when that service needs them.

`COMPOSIO_API_KEY` is required only on services running Layer 1 Composio drivers during integration and production, per ADR-0129 and ADR-0132. Mock-first local development and CI eval runs do not require it.

Layer 1 adapters may use `INTEGRATION_DRIVER=mock` by default and `INTEGRATION_DRIVER=composio` when optional live Composio is configured per ADR-0137.

## Production deployment

Each deployable service has its own Dockerfile:

- `apps/workbench/Dockerfile` → Cloud Run service `toee-hermes-workbench`
- `services/hermes-gateway/Dockerfile` → Cloud Run service `toee-hermes-gateway`

Production secrets are injected through GCP Secret Manager into Cloud Run environment variables or secret mounts. Local `.env.local` files are not used in production.

Additional GCP services remain demand-driven per ADR-0025.

**Considered options:** one multi-target Dockerfile for both services (rejected—weak independent deploy and scaling); require docker-compose for all local development (rejected—slower iteration on Windows and macOS); single shared `.env` for all secrets (rejected—mixes workbench session secrets with public webhook credentials).
