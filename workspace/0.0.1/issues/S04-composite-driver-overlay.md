# S04 — Composite driver overlay (`extra_drivers`)

- **Milestone:** 0.0.1 / M1
- **Size:** M
- **Depends on:** S02
- **Delivers:** FR-2
- **Surface:** plugin driver selector + hermes-runtime boot

## Goal

Route `toee_customer_memory` on the live external turn to the Postgres datastore,
while every other tool keeps its mock/composio driver — with no governance drift
and no psycopg dependency in the plugin.

## Problem

`_build_driver_selector` (`hermes/toee_hermes/plugin/__init__.py`) knows only
mock/composio; `toee_customer_memory` is not a Composio Layer-1 tool, so it always
resolves to the ephemeral mock — writes never persist.

## Files (likely)

- `hermes/toee_hermes/plugin/__init__.py` — `_build_driver_selector`, `_register`,
  `register_turn` gain an optional `extra_drivers: dict[str, ToolDriver]`
  (per-tool override, checked before mock/composio).
- `hermes/toee_hermes/boot.py` — thread `extra_drivers` through `boot_profile`.
- `hermes-runtime/hermes_runtime/openrouter.py` (and the boot caller) — inject
  `{"toee_customer_memory": PostgresDriver(dsn=...)}`. psycopg stays in
  hermes-runtime; the plugin only sees a `ToolDriver`.

## Approach

- Selector precedence: `extra_drivers[tool]` → composio (Layer 1) → mock.
- The injected `PostgresDriver` carries `kind = "datastore"`, so audit rows are
  correctly attributed and the gate/allowlist run unchanged before it.

## Acceptance

- Unit: selector returns the injected driver for `toee_customer_memory`, mock for
  others; composio path unaffected.
- Integration (with S06/S03): a live-turn upsert lands in `customer_memory_slot`
  with a `driver.kind = "datastore"` audit row (anti-mock check).

## Out of scope

- No-DB degradation (S05); read injection (S06–S08).
