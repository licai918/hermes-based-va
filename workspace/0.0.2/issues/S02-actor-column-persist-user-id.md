# S02 — Actor column + persist the acting rep

- **Milestone:** 0.0.2 — memory governance
- **Size:** S
- **Depends on:** none
- **Delivers:** FR-4, R2, NFR-1, RK-6
- **Surface:** datastore schema + memory handler

## Goal

Record the acting employee on every memory write when one exists — a UI
correction carries the rep's account id, an AI draft/merge write carries null —
so the audit trail is attributable.

## Problem

`customer_memory_slot` (`hermes-runtime/migrations/0001_initial_schema.sql:77-88`)
has **no actor column**. `_upsert_preference`
(`hermes-runtime/hermes_runtime/datastore/handlers/memory.py:50-82`) inserts 7
columns and **drops `context.user_id`**. The actor arrives via
`hermes-runtime/hermes_runtime/tool_dispatch_app.py:190-204`
(`actor_account_id → context.user_id`) but is thrown away, so a rep's deliberate
correction is indistinguishable from an AI draft write. This is the NFR-3 gap
0.0.1 resolved then dropped.

## Files (likely)

- `hermes-runtime/migrations/` — new migration adding a **nullable** actor column
  to `customer_memory_slot` (no backfill).
- `hermes-runtime/hermes_runtime/datastore/handlers/memory.py` —
  `_upsert_preference` (:50-82): thread `context.user_id` into the insert.
- `hermes-runtime/hermes_runtime/tool_dispatch_app.py:190-204` — actor source
  (already maps `actor_account_id → context.user_id`).
- `hermes-runtime/tests/test_datastore_driver_memory.py`,
  `test_customer_memory_datastore.py` + a migrate test.

## Approach

Per PRD §9 (actor nullable; AI-draft and merge → null; UI correction → rep id;
NFR-1 / RK-6):

- New migration: add the actor column **nullable, no backfill, no read
  dependency** until this slice lands (RK-6 — safe ALTER on a live table).
- Thread `context.user_id` into `_upsert_preference`'s insert: UI dispatch → rep
  account id; draft-turn / merge → NULL.

## Acceptance

- Datastore **R2** (§6.3 FR-4 seam): a UI-correction row carries the rep's actor;
  an AI-draft row's actor is null — both read back **directly from Postgres**.
- Migration test: the ALTER applies clean; existing rows land NULL (no backfill).

## Out of scope

- Deriving `source` — **S01**.
- The `user_id`-presence invariant write-up (UI ⟺ actor present) — **S11** ADR.
