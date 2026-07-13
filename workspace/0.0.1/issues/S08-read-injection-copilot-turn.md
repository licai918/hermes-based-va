# S08 — Read injection — Copilot turn

- **Milestone:** 0.0.1 / M1
- **Size:** M
- **Depends on:** S02, S06
- **Delivers:** FR-1 (Copilot surface)
- **Surface:** copilot async turn

## Goal

When an employee works a case, the Copilot draft turn sees the same customer
preference block (ADR-0113 Copilot behavior).

## Problem

`make_copilot_run_turn` (`hermes-runtime/hermes_runtime/copilot_turn.py`) is a
**separate injection seam** from the external turn, and it is bound to a
`case_id`, not a phone — the binding key must be derived from the case's thread
identity.

## Files (likely)

- `hermes-runtime/hermes_runtime/copilot_turn.py` — `run_turn(*, channel, case_id,
  prompt)`.
- A case→binding lookup: from `case_id` → `customer_thread` identity (verified
  `shopify_customer_id` or the thread's channel identity).

## Approach

- Resolve the binding key from the case's thread identity (reuse the workbench read
  path that already loads a case's thread).
- Load slots (S06) and inject via the same `render_injection` block used
  externally; gated by `memory_enabled()` (S05).

## Acceptance

- Integration/E2E: opening a case whose customer has stored preferences injects
  the correct block into the Copilot draft turn.
- Isolation: a different case/customer never sees another's block.

## Out of scope

- Employee write/correct flow (already governed via `toee_customer_memory` on the
  internal profile; `source = employee_confirmed` handled in S03).
