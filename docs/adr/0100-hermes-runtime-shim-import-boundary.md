# Hermes runtime shim as the only official SDK import boundary

> **Superseded by ADR-0139.** No TS `packages/hermes-runtime` shim exists. The
> import boundary is now: only the Python Hermes-integration layer (the
> `toee_hermes` plugin and the gateway embedding) may import `hermes_agent` /
> `run_agent`; `apps/workbench` never imports Hermes and uses the API Server.

Only `packages/hermes-runtime` may import official Hermes packages. `apps/workbench`, `services/hermes-gateway`, and UI code must not import Hermes SDK modules directly.

`packages/domain-adapters` implements official Hermes Tool, Skill, or MCP interfaces and is registered into Hermes through `packages/hermes-runtime`. Domain adapters must not import Hermes private or internal module paths.

## Allowed official capabilities

`packages/hermes-runtime` may use official Hermes public APIs for:

- runtime startup and shutdown
- **Hermes Profile** selection
- Tool, Skill, and MCP registration
- **Hermes Native Memory** reads and writes
- official **Profile Tool Allowlist** and **Tool Gate** enforcement
- approved **Hermes Built-in Tools** such as `web_search` and `web_extract` under existing ADR restrictions

## Forbidden custom implementations

The repository must not implement parallel replacements for:

- agent planner or ReAct orchestration loops
- memory schemas or stores outside **Hermes Native Memory**
- profile permission systems
- tool routing or allowlist enforcement
- eval execution engines that bypass the repository **Launch Eval Runner** for go-live decisions

`apps/workbench` and `services/hermes-gateway` may contain ingress, auth, UI, and BFF orchestration, but not agent-core behavior.

## Dependency flow

```text
apps/workbench ─────────────┐
services/hermes-gateway ────┼→ packages/hermes-runtime → official Hermes public SDK
packages/domain-adapters ───┘
```

When an official Hermes release adds a capability that overlaps with local code, local code should be removed in favor of the native path per ADR-0099.

**Considered options:** allow direct Hermes imports from apps and services (rejected—upgrade changes spread across the repo); import only one core package and rebuild memory and profile behavior locally (rejected—breaks native-first goal); let domain adapters call Hermes private modules directly (rejected—fragile across official upgrades).
