# S03 — Write discipline: framework `source`, `evidence`, caps

- **Milestone:** 0.0.1 / M1
- **Size:** M
- **Depends on:** S02, S04
- **Delivers:** FR-3, correctness R4, RK-1
- **Surface:** memory handlers + tool schema

## Goal

Make the hard write guards real (framework-controlled), so the model cannot
mislabel or over-write preferences.

## Problem

`source` is a model-supplied param today (`params.get("source")`), so the model
could tag an inferred write as `customer_explicit`. Length cap and source enum are
not enforced.

## Files (likely)

- `hermes-runtime/hermes_runtime/datastore/handlers/memory.py` — `_upsert_preference`.
- `hermes/toee_hermes/drivers/mock/memory.py` — mirror.
- `hermes/toee_hermes/tool_catalog.py` — `toee_customer_memory.upsert_preference`
  schema: add optional `evidence`; `source` is **not** a model input.

## Approach

- `source` is set by the framework from the calling profile/context:
  external turn → `customer_explicit`; Copilot → `employee_confirmed`; merge (S10)
  → `merged_provisional`. Reject any other value; ignore a model-supplied `source`.
- Enforce `value ≤ 200 chars`; reject open-ended keys (exists) with the same error
  class.
- Add optional `evidence` param (verbatim customer phrase), stored/audited for the
  write. (Approved decision.)

## Acceptance

- Unit R4: over-length value rejected; open-ended key rejected; `source` cannot be
  forged via params; `evidence` persisted.
- Eval scenario 26 (no-inferred-write) stays green on the real path (S14).

## Out of scope

- The composite-driver wiring that routes this to Postgres (S04).
- The "explicit statement" model behavior itself (persona/eval, not code).
