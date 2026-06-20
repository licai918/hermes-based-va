# Shared Hermes runtime package embedded in workbench and gateway

> **Superseded by ADR-0139.** This ADR assumed an in-process Node/TypeScript
> Hermes SDK embedded via `packages/hermes-runtime`. Hermes is the Nous Research
> Python agent; integration is via a Python plugin, profiles, and library/API-server
> embedding. The intent (no extra runtime service, shared profiles/tools) is
> preserved in ADR-0139.

Both `apps/workbench` and `services/hermes-gateway` invoke **Hermes Core** through a shared `packages/hermes-runtime` library. v1 does not add a separate Hermes runtime Cloud Run service and does not route workbench traffic through the gateway for agent execution.

## Package responsibility

`packages/hermes-runtime` wraps the Hermes Core native SDK and provides service-local helpers to:

- boot or reuse a Hermes runtime instance inside the current Node process
- select the active **Hermes Profile**
- register `packages/domain-adapters` tools for that profile
- read and write **Hermes Native Memory** through Hermes APIs

Business rules remain in `packages/domain-adapters`. Orchestration, profile allowlists, and memory stay in Hermes.

## Call patterns

**Workbench**

`apps/workbench` BFF handlers import `packages/hermes-runtime` directly and call profile-specific helpers such as:

- `runProfile("internal_copilot", ...)`
- `runProfile("supervisor_admin", ...)`

Copilot chat, case reads, governed send, and admin governance actions all execute inside the workbench Cloud Run process.

**Gateway**

`services/hermes-gateway` imports the same package and calls:

- `runProfile("customer_service_external", ...)`

only from the external channel pipeline after webhook verification and ingress matching.

## Service boundary rule

`apps/workbench` must not call `services/hermes-gateway` over HTTP for Copilot or admin operations. The gateway remains public channel ingress and external runtime only.

Both services may evolve independently, but they must use the same `packages/hermes-runtime` and `packages/domain-adapters` versions to avoid profile or tool drift.

**Considered options:** workbench HTTP calls to gateway internal routes (rejected—couples employee workflows to public ingress service); third standalone Hermes runtime service on day one (rejected—extra Cloud Run surface without proven need); duplicate Hermes bootstrapping code in each app (rejected—profile and tool registration drift risk).
