# S01 — Source discriminator: `copilot_agent` via `user_id` presence

- **Milestone:** 0.0.2 — memory governance
- **Size:** S
- **Depends on:** none
- **Delivers:** FR-2, R1, RK-1, RK-2
- **Surface:** memory write-source resolver (mock + datastore)

## Goal

Give an AI draft-turn write its own honest `source` (`copilot_agent`),
discriminated from a rep's confirmed correction by whether an acting employee is
present — framework-derived, never model-supplied.

## Problem

`resolve_memory_write_source(context)`
(`hermes/toee_hermes/drivers/mock/memory.py:233-259`) maps INTERNAL →
`employee_confirmed` on the **profile alone**. So an autonomous AI draft-turn
write (the S20 plumbing) is tagged `employee_confirmed` even though **no employee
confirmed it** — contradicting ADR-0111's "writes happen after employee
confirmation." `MEMORY_SOURCE_VALUES` (:40-44) has only `customer_explicit`,
`employee_confirmed`, `merged_provisional` — no honest label for a draft write.

## Files (likely)

- `hermes/toee_hermes/drivers/mock/memory.py` — `resolve_memory_write_source`
  (:233-259); add `copilot_agent` to `MEMORY_SOURCE_VALUES` (:40-44). One shared
  resolver; the datastore handler imports it.
- `hermes/tests/test_memory.py`, `hermes/tests/test_customer_memory_write_source.py`
  — unit seam.
- `hermes-runtime/tests/test_datastore_driver_memory.py` — datastore seam.

## Approach

Per PRD §9 (discriminator = `context.user_id` presence):

- INTERNAL **+ `context.user_id`** → `employee_confirmed`; INTERNAL, **no
  `user_id`** → `copilot_agent`; EXTERNAL → `customer_explicit`; merge path stays
  `merged_provisional` (unchanged).
- Add `copilot_agent` to `MEMORY_SOURCE_VALUES`. `source` is `text` — **no
  migration** (NFR-1).
- `source` is never read from model params (RK-1/2: the label makes an inferred
  write visible even if a prompt slip lands one).

## Acceptance

- Unit **R1** (§6.3 FR-2 seam): INTERNAL+`user_id` → `employee_confirmed`;
  INTERNAL no `user_id` → `copilot_agent`; EXTERNAL → `customer_explicit`; merge →
  `merged_provisional`; the model cannot forge any of these via tool params.
- Datastore (live Postgres): a UI-dispatched correction persists
  `source=employee_confirmed`; an AI draft-turn write persists
  `source=copilot_agent` — read back **directly from Postgres**.

## Out of scope

- The actor column / persisting the rep id — **S02**.
- The draft-persona rule discouraging inferred writes — **S03**.
