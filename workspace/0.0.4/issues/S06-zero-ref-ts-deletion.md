# S06 — Delete zero-reference TS scaffold

- **Milestone:** 0.0.4 — durable substrate
- **Track:** T3 TS cleanup
- **Size:** XS
- **Depends on:** none — can land first
- **Delivers:** FR-15
- **Surface:** deletion only; no product code

## Goal

FR-15: `services/hermes-gateway` (Fastify server never built, superseded by
Python `gateway_app.py`) and `packages/hermes-runtime` (stub voided by
ADR-0139) are deleted, along with the dead `@toee/hermes-runtime` dependency
line in `apps/workbench/package.json`.

## Approach

- Verify zero code imports one more time at delete time (grep), then delete
  both trees; drop the dep line; update `pnpm-workspace.yaml` /
  `vitest.workspace.ts` / `tsconfig.base.json` references if any.

## Acceptance — three-layer gate (pure-refactor carve-out)

- **① Technical:** full CI green on the cleaned tree (typecheck, vitest,
  pytest, eval replay); `pnpm install` lockfile updates cleanly.
- **② E2E:** carve-out — no behavior surface; CI run page as evidence.
- **③ Product (PAC):** feeds PAC-5 at S12.

## Out of scope

- `packages/domain-adapters` / `packages/eval-runner` — **S11** (blocked on
  S07+S09).
