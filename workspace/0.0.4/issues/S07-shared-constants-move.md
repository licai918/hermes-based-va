# S07 — Move workbench-needed constants to packages/shared

- **Milestone:** 0.0.4 — durable substrate
- **Track:** T1 API-only workbench
- **Size:** S
- **Depends on:** none
- **Delivers:** FR-6
- **Surface:** `packages/shared` + workbench imports; no behavior change

## Goal

FR-6: everything the workbench imports from `@toee/domain-adapters` that is a
shared *contract* rather than mock *behavior* — `MEMORY_PREFERENCE_SLOTS`,
referenced tool result types — moves to `packages/shared`, so S09/S11 can
delete the package without orphaning contracts.

## Approach

- Inventory workbench imports from `@toee/domain-adapters`
  (`lib/gateway/types.ts:6`, `lib/bff/copilot/deps.ts:9`, tests).
- Move constants/types to `packages/shared` (single source; Python side
  already has its own authoritative copy — note the pairing in the module
  header per repo convention); update imports. `executeTool`/mock-driver
  imports stay untouched (they die with the fallback in S09).

## Acceptance — three-layer gate (pure-refactor carve-out)

- **① Technical:** typecheck + vitest green; no `@toee/domain-adapters`
  import of constants/types remains in workbench source (grep-proof in PR).
- **② E2E:** carve-out — no behavior surface.
- **③ Product (PAC):** none (mechanical move).

## Out of scope

- Deleting the package — **S11**. Touching the mock execution path — **S09**.
