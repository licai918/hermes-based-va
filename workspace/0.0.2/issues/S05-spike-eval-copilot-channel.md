# S05 — SPIKE: eval-harness Copilot-channel capability

- **Milestone:** 0.0.2 — memory governance
- **Size:** S
- **Depends on:** none
- **Delivers:** RK-5 (gates S07)
- **Surface:** eval harness (spike — no production code)

## Goal

Decide go/no-go on whether the eval runner can drive an `internal_copilot` draft
turn — the capability FR-3's copilot no-inferred scenario needs — **before S07 is
sized**.

## Problem

Eval scenarios are `channel: textline` today (e.g. scenario 26,
`eval/scenarios/26-customer-memory-no-inferred-write.yaml`). FR-3 needs a
copilot-path scenario; if the runner (`hermes/eval_runner/`) cannot dispatch an
`internal_copilot` draft turn, S07 needs harness plumbing and FR-3 grows S→M
(RK-5). PRD §6.3: **no FR-3 implementation slice starts until this spike
resolves.**

## Files (likely — investigated, not changed)

- `hermes/eval_runner/` — the runner / dispatch path.
- `eval/scenarios/26-customer-memory-no-inferred-write.yaml` — the `textline`
  reference scenario.

## Approach

Per PRD §6.3 spike-gate / RK-5:

- Trace whether the runner can set profile `internal_copilot` / drive a draft
  turn; prototype a throwaway scenario if that is the fastest read.
- Output = a **go/no-go note** + the exact harness change required if "no". **No
  production code.**

## Acceptance

- A written go/no-go recorded (in this slice or EXPLORATION): can the runner drive
  an `internal_copilot` draft turn — yes/no.
- If no: the specific harness change S07 must carry is named, and FR-3 is re-sized
  S→M.
- S07 does not start until this resolves.

## Out of scope

- The scenario itself and any production/harness code — **S07**.
