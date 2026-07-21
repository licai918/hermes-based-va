# S11 — Delete TS mock packages + API-only ADR

- **Milestone:** 0.0.4 — durable substrate
- **Track:** T3 TS cleanup
- **Size:** S
- **Depends on:** S07, S09
- **Delivers:** FR-16, FR-17
- **Surface:** deletion + workspace config + ADR

## Goal

FR-16: with the fallback gone, `packages/domain-adapters` and
`packages/eval-runner` (TS) are deleted; the TS side ends at `apps/workbench`
+ `packages/shared`. FR-17: the API-only ADR ships.

## Approach

- Verify no remaining imports (S07 moved contracts; S09 deleted the mock
  execution path; check `packages/eval-runner` is unreferenced by CI), then
  delete both trees.
- Update `pnpm-workspace.yaml`, `vitest.workspace.ts`,
  `tsconfig.base.json`, lockfile.
- **API-only ADR**: Slice-2 dual-path architecture formally retired; the
  HTTP client seam is the workbench's only backend seam; the deletion set
  recorded (this slice + S06).

## Acceptance — three-layer gate (pure-refactor carve-out)

- **① Technical:** full CI green on the cleaned tree; grep-proof no
  `@toee/domain-adapters` / TS `eval-runner` references remain.
- **② E2E:** carve-out — S10's walkthrough re-run on the cleaned tree.
- **③ Product (PAC):** PAC-5 at S12.

## Out of scope

- `packages/shared` and `apps/workbench` stay. Python `hermes/eval_runner`
  untouched (it is the live one).
