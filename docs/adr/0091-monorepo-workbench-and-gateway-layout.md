# Monorepo layout with separate workbench and gateway services

The first-version **Hermes VA** codebase uses one repository with separate deployable services and shared packages.

## Top-level layout

| Path | Purpose | Cloud Run service |
|------|---------|-------------------|
| `apps/workbench` | Next.js **Copilot Workbench** and **Admin Governance Console** UI plus workbench BFF API routes | `toee-hermes-workbench` |
| `services/hermes-gateway` | **Channel Gateway**, ingress identity matching, and **Hermes Core** runtime invocation for external channels | `toee-hermes-gateway` |
| `packages/domain-adapters` | Toee Tire **Domain Adapter Tools** implementing ADR-0059 and ADR-0070 action enums | shared library |
| `packages/shared` | Shared TypeScript types, route constants, tool names, and profile identifiers | shared library |
| `eval` | Launch eval fixtures, mocks, and runner | CI and staging tooling |
| `docs` | `CONTEXT.md`, ADRs, and agent docs | not deployed |

## Service boundaries

`apps/workbench` serves authenticated employee traffic only. It does not receive public Textline webhooks.

`services/hermes-gateway` serves external channel ingress and **External Customer Service Profile** runtime traffic. It does not serve the internal workbench UI.

Both services may import `packages/domain-adapters` and `packages/shared`, but each service keeps its own deployable entrypoint and Cloud Run configuration.

## Provisioning rule

Additional infrastructure such as database, queue, cache, or scheduler services is added only when a concrete feature in `apps/workbench`, `services/hermes-gateway`, or **Hermes Native Memory** requirements proves the need, per ADR-0025.

**Considered options:** one full-stack Next.js app for UI and webhooks (rejected—blurs public ingress and internal admin security boundaries); separate repositories for workbench and gateway (rejected—extra coordination cost for a small launch team); pre-provision a fixed database and cache bundle in the repo scaffold (rejected—conflicts with demand-driven Cloud Run provisioning).
