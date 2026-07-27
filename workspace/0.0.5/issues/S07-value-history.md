# S07 — L4 value history: `preference_updated` audit rows

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T2 Lifecycle core
- **Size:** S
- **Depends on:** none
- **Delivers:** FR-9
- **Surface:** `_upsert_preference` (mock+PG); Memory Audit console history

## Goal

FR-9 (closes verified gap 1): every L4 overwrite records `preference_updated` with
`{old_value, new_value}` in details — value-change history becomes auditable and rollback
becomes possible. US5. Exploration C5 §5.3.

## Approach

- `_upsert_preference` reads the current value (already in-transaction) and writes ONE
  `insert_audit(action="preference_updated", details={slot, old_value, new_value})` row when
  the value actually changes (no row on identical writes — idempotent noise-free); mock twin
  in lockstep (NFR-7).
- `get_memory_audit` already returns unfiltered audit actions (S20 design) — the supervisor
  view's history gains the rows for free; add old→new rendering.
- Conflict-rate metric groundwork: differing-value overwrites are now countable (consumed by
  S22).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** live-PG — an overwrite writes exactly one row with correct old/new; an
  identical write adds none; ADR-0148 invariants + removal tripwire green; mock parity.
- **② E2E (browser):** change a preference in the copilot panel → the Memory Audit history
  shows old→new; screenshot.
- **③ Product (PAC):** PAC-3's history leg.

## Out of scope

- Rollback ACTION (view+audit only this iteration). Conflict-rate tile — **S22**.
