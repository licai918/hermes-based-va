# S09 — Single-source the preference-slot list on the TS side

- **Milestone:** 0.0.2 — memory governance
- **Size:** S
- **Depends on:** none
- **Delivers:** FR-7
- **Surface:** TS domain-adapters / workbench

## Goal

Export the four preference slots **once** from `@toee/domain-adapters` and import
them in the workbench, so a fifth slot cannot silently drift between copies.

## Problem

`PREFERENCE_SLOTS` is a hand-written literal at
`apps/workbench/lib/gateway/types.ts:120`, while `MEMORY_PREFERENCE_SLOTS` is a
module-**local, unexported** const at
`packages/domain-adapters/src/mock/memory.ts:28`. Two hand-copied lists → a new
slot can drift between them.

## Files (likely)

- `packages/domain-adapters/src/mock/memory.ts:28` — export
  `MEMORY_PREFERENCE_SLOTS`.
- `apps/workbench/lib/gateway/types.ts:120` — import it instead of re-declaring
  `PREFERENCE_SLOTS`.
- `apps/workbench` vitest.

## Approach

Per FR-7, §6.3 FR-7 seam:

- Export the const from the shared package; import it in the workbench. The Python
  copy (`hermes/toee_hermes/drivers/mock/memory.py:27`) stays a **documented
  parallel** — cross-language sharing is out of scope.

## Acceptance

- Workbench vitest (§6.3 FR-7 seam): the workbench imports the slot constant
  rather than re-declaring it; adding a slot in the shared package propagates to
  the workbench.

## Out of scope

- Cross-language (Python) sharing — the Python copy stays a documented parallel.
