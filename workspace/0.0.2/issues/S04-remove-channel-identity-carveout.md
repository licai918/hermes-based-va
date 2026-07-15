# S04 — Remove the `channel_identity_id` carve-out + tripwire + test updates

- **Milestone:** 0.0.2 — memory governance
- **Size:** S
- **Depends on:** none
- **Delivers:** FR-5, R3, RK-4
- **Surface:** memory binding resolver

## Goal

Bind customer memory from context only; a write on an unresolvable case **fails
closed (`policy_blocked`)**, never bound to a model-named `provisional:{param}`
key.

## Problem

`resolve_customer_memory_binding`
(`hermes/toee_hermes/drivers/mock/memory.py:215-224`) has an `internal_copilot`
fallback that returns `provisional:{channel_identity_id}` from **model params** —
the last path by which a draft model can name a binding key. S16 case-identity
resolution superseded it as the primary path, but the carve-out is still live.

## Files (likely)

- `hermes/toee_hermes/drivers/mock/memory.py` — remove the `INTERNAL` param
  fallback (:215-224); unresolvable identity → `policy_blocked`.
- `hermes-runtime/tests/test_datastore_driver_memory.py` — **delete** the S15
  characterization test
  `test_dispatch_route_correction_persists_but_misses_a_verified_customers_read_key`
  (:194); update the assertion at :180 to `policy_blocked`; add a removal-tripwire
  test.
- `hermes/tests/test_customer_memory_binding.py:115`,
  `hermes/tests/test_memory.py:407` — update to assert `policy_blocked`.

## Approach

Per PRD §9 (carve-out removed; S15 test deleted; 3 tests updated) and §6.0.4
(removal tripwire); RK-4:

- Delete the `if context.profile == INTERNAL: … return
  f"provisional:{channel_identity_id}"` branch — binding derives **solely** from
  `binding_key_from_identity(context.identity)`; `None` → `policy_blocked`.
- Add a removal tripwire: a model-supplied `channel_identity_id` on INTERNAL must
  be `policy_blocked`. If that test ever shows a bound `provisional:{…}` key, the
  carve-out has silently returned — CI treats it red.

## Acceptance

- Unit **R3** (§6.3 FR-5 seam): a model-supplied `channel_identity_id` no longer
  binds → `policy_blocked`.
- Datastore (live Postgres): an unresolvable-identity write is blocked, not
  param-bound; the UI dispatch route (`case_id` → identity) is unaffected.
- Removal tripwire present; the S15 characterization test **deleted**; the 3
  carve-out tests assert `policy_blocked`.

## Out of scope

- `source`/actor labelling — **S01/S02**.
- The ADR recording the removal — **S11**.
