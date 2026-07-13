# S06 — `load_customer_memory` in the gateway store

- **Milestone:** 0.0.1 / M1
- **Size:** S
- **Depends on:** S02
- **Delivers:** FR-1 (read foundation)
- **Surface:** PostgresGatewayStore

## Goal

Provide a single indexed read of a customer's preference slots by binding key, for
the injection paths to consume.

## Files (likely)

- `hermes-runtime/hermes_runtime/postgres_gateway_store.py` — add
  `load_customer_memory(binding_key: str) -> list[{"slot": str, "value": str}]`.

## Approach

- Reuse the `_get_preferences` SELECT shape
  (`SELECT slot_name, slot_value FROM customer_memory_slot WHERE binding_key = %s`),
  returning the `{slot, value}` list shape `hooks._render_memory` already expects.
- Honor the store's two connection modes (injected conn vs dsn), matching the
  existing methods.

## Acceptance

- Datastore integration: after an upsert for a binding key, `load_customer_memory`
  returns exactly the stored slots; unknown key → empty list.
- Return shape matches `_render_memory` input (no adaptation needed downstream).

## Out of scope

- Choosing the binding key at turn time and injecting (S07/S08).
