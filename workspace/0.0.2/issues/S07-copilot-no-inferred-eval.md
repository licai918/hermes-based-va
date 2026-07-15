# S07 — Copilot no-inferred eval scenario (mechanical, hard gate)

- **Milestone:** 0.0.2 — memory governance
- **Size:** S
- **Depends on:** S05 (spike), S03 (guard to test)
- **Delivers:** FR-3, R4
- **Surface:** eval scenario

## Goal

A new **mechanical** copilot-path no-inferred-write scenario that hard-gates FR-1
— the draft agent must not persist a preference it merely inferred.

## Problem

FR-1's draft-persona guard (S03) is soft (model behaviour); without a regression
eval a future prompt edit could silently re-open inferred writes. External
scenario 26 guards the external path, but there is no copilot equivalent.

## Files (likely)

- `eval/scenarios/30-copilot-memory-no-inferred-write.yaml` — new, mirroring
  `26-customer-memory-no-inferred-write.yaml`'s
  `memory_assertions.forbid_inferred_upsert` + `tool.forbidden_tools`, on the
  `internal_copilot` draft path.
- any harness change the **S05** spike identified.

## Approach

Per FR-3 (mechanical hard gate), R4, §6.3 FR-3 replay seam:

- Mirror 26's mechanical assertions (`forbid_inferred_upsert` / `did_upsert` +
  `forbidden_tools`) — **mechanical, deterministic, hard gate** (NFR-3).
- Depends on **S03** (a guard to test) and **S05** (the spike's go/no-go on
  driving a copilot draft turn; carry any harness plumbing it named).

## Acceptance

- Eval **R4** (§6.3 FR-3 hard-gate seam): the copilot no-inferred scenario is
  **green on the hard gate** — the draft agent does not persist an inferred
  preference (`did_upsert` false / forbidden tool not called).

## Out of scope

- The persona rule itself — **S03**.
- The honored / no-unprompted-recall semantic legs and the judge — **S06/S08**.
