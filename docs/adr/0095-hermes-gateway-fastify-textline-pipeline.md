# Hermes gateway Node Fastify service with Textline webhook pipeline

> **Amended by [ADR-0139](0139-hermes-is-nous-python-agent-plugin-integration.md).**
> The Textline pipeline stages below (verify → normalize → ingress match → run
> External profile) still hold, but the gateway is the **Python FastAPI** service
> in `hermes-runtime/`, not a Node Fastify service — it embeds the upstream Python
> `hermes-agent` via the library. The "build a Python FastAPI gateway (rejected)"
> option at the end was reversed by ADR-0139. Deploy details live in
> `docs/ops/deploy-cloud-run.md`; this ADR is retained as historical record.

`services/hermes-gateway` is a standalone Node.js service deployed to Cloud Run for external channel ingress and **External Customer Service Profile** runtime execution.

## Runtime stack

The gateway uses Fastify as the HTTP server and embeds or invokes the Hermes Core native runtime. It does not reimplement Hermes orchestration, profile allowlists, or memory semantics.

The service imports shared business logic from `packages/domain-adapters` and `packages/shared`.

## Public routes

| Route | Purpose |
|-------|---------|
| `GET /healthz` | Liveness and readiness for Cloud Run |
| `POST /webhooks/textline` | Textline inbound webhook ingress |

Future channel routes such as email or voice webhooks may be added under `src/routes/webhooks/` without changing the workbench service boundary.

## Textline processing pipeline

`POST /webhooks/textline` runs this server-side pipeline before agent execution:

1. verify Textline webhook authenticity per ADR-0021
2. normalize the inbound event into a channel payload
3. perform **Ingress Phone Match** and bind the Textline conversation to the current **SMS Session** per ADR-0043
4. invoke **Hermes Core** under the **External Customer Service Profile**

Failed signature or token validation returns `401` and does not enter agent processing.

## Service layout

```text
services/hermes-gateway/
├── src/
│   ├── server.ts
│   ├── routes/
│   │   ├── health.ts
│   │   └── webhooks/textline.ts
│   ├── pipeline/
│   │   ├── verify-textline.ts
│   │   ├── normalize-inbound.ts
│   │   └── run-external-profile.ts
│   └── hermes/
│       └── runtime.ts
```

`apps/workbench` does not expose public Textline webhooks and does not host external customer-service agent execution in v1.

**Considered options:** make the Hermes official process itself the only HTTP server with no thin gateway layer (rejected—less explicit place for ingress verification and channel normalization); implement webhooks as Next.js routes in `apps/workbench` (rejected—blurs employee and public ingress boundaries); build a Python FastAPI gateway (rejected—splits the Node monorepo runtime model without a documented Hermes requirement).
