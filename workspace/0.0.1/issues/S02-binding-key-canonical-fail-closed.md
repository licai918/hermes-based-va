# S02 — Canonical binding key + fail-closed resolve

- **Milestone:** 0.0.1 / M1
- **Size:** S
- **Depends on:** S01
- **Delivers:** FR-5, correctness R1, R6
- **Surface:** memory handlers (datastore + mock)

## Goal

Resolve the Customer Memory binding key from context only, in one canonical form,
and fail closed when no identity is resolvable.

## Problem

`_resolve_binding` (`hermes-runtime/hermes_runtime/datastore/handlers/memory.py`
and the mock twin) today: (a) reads `channel_identity_id` from **model params**
for non-verified callers, and (b) falls back to a bare `"provisional"` key shared
by all anonymous callers — a cross-customer leak.

## Files (likely)

- `hermes-runtime/hermes_runtime/datastore/handlers/memory.py` — `_resolve_binding`.
- `hermes/toee_hermes/drivers/mock/memory.py` — keep the mock twin identical.
- reuse `normalize_e164` (`toee_hermes/gateway/normalize.py`).

## Approach

- Verified → `shopify_customer_id`, `binding_kind = "verified"`.
- Else, read the channel identity from `context.identity` (S01), key
  `provisional:{channel}:{E.164}` e.g. `provisional:sms:+17786803250`,
  `binding_kind = "provisional"`.
- No channel identity in context → raise `policy_blocked` (never the bare
  `"provisional"` key). The `channel_identity_id` param is honored **only** for
  the Copilot employee-confirmed path (profile = internal_copilot).

## Acceptance

- Unit R1: verified vs provisional key chosen correctly from identity outcome.
- Unit R6: no channel identity → `policy_blocked`; a model-supplied phone param on
  the external profile cannot change the binding.
- Canonical form asserted: `provisional:sms:+17786803250`.

## Out of scope

- Reading/injecting the resolved slots (S06/S07/S08).
- No table migration (the table has never been written by the live path).
