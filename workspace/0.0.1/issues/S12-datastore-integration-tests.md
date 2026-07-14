# S12 — Datastore integration tests (R1–R6)

- **Milestone:** 0.0.1 / M1
- **Size:** M
- **Depends on:** S02, S03, S06, S10 (write TDD-style alongside)
- **Delivers:** §6.2 correctness at the datastore level, §6.3 test-level
- **Surface:** `hermes-runtime/tests/`

## Goal

Prove the correctness rules on real Postgres, reading back directly from the DB
(anti-mock principle §6.0.1).

## Files (likely)

- New `hermes-runtime/tests/test_customer_memory_datastore.py` — same throwaway-
  schema harness as `test_postgres_gateway_store.py` (query via `conn.cursor()`).

## Coverage

- R1 binding selection (verified / provisional canonical key).
- R2 content round-trip (stored value == loaded value).
- R3 cross-customer isolation (two binding keys; B never sees A; A still sees own).
- R4 write discipline (open-ended key rejected; >200 rejected; framework `source`;
  `evidence` stored).
- R5 merge three-state + provisional deletion + idempotent audit.
- R6 fail-closed (no channel identity → `policy_blocked`; model phone param can't
  cross-bind).

## Acceptance

- All of R1–R6 green against real Postgres; every persistence assertion reads the
  DB directly (not a tool return).

## Out of scope

- The live-turn E2E and eval scenarios (S13/S14).
