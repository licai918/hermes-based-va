# S11 — Whole-binding erase + deletion-success tripwire

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T2 Lifecycle core
- **Size:** S
- **Depends on:** none
- **Delivers:** FR-13, FR-14
- **Surface:** governed erase action (loops existing clears); metric + tripwire

## ⚠ Pre-flight corrections — BINDING (see [../DECISIONS.md](../DECISIONS.md))

- **D10** — `merge_provisional_memory` copies provisional slots from EVERY linked channel
  identity onto the verified key on the next verified turn, so an erase that only clears the
  verified binding is silently undone by the customer's next message from a linked channel.
  This slice must clear the linked provisional bindings too (every channel identity linked to
  the binding), inside the same governed action, each with its own audit row. The Acceptance
  below is INVERTED as a result: a post-erase merge must NOT restore any slots and must NOT
  fire the re-appearance alert; the alert now fires only on a genuinely unexpected write, not on
  the erase's own aftermath.
- **D17** — this is one of the five serialized catalog-touching slices (S01 → S02 → S15 → S11 →
  S10). Only one of them is in flight at a time — confirm S15 has landed and S10 has not started
  before you touch the shared nine-file sync set.

## Goal

FR-13: one supervisor action erases a customer's whole memory binding — a governed LOOP over
the existing per-slot `clear_preference` (per-slot audit rows + one summary row), no new write
primitive. FR-14: deletion-success metric — cleared-and-stayed-cleared; a re-appearance (a
merge or proposal recreating an erased slot) alerts. US7. Exploration C5 §5.6.

## Approach

- `erase_customer_memory` admin-only action (`_AGENT_EXCLUDED_ACTIONS` — **with the house
  `registered_names()` exclusion regression test**, gap-audit fix): iterate the four slots
  through the EXISTING clear (shared `resolve_clear_authorization` gate untouched), write a
  summary audit row with per-slot outcomes; mock+PG lockstep.
- Memory Audit console gains the one-click button (confirm dialog).
- Re-appearance tripwire: a metric/report flagging any slot write on a binding within N days
  of its erase summary (deterministic query; surfaces on S22's panel; N documented).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** live-PG — erase removes all slots + writes 4+1 audit rows attributed to the
  supervisor; policy_blocked without actor; a post-erase provisional merge triggers the
  re-appearance flag in the query; tripwires green.
- **② E2E (browser):** one click erases a seeded customer; history shows the full trail;
  screenshot.
- **③ Product (PAC):** PAC-3's erase leg.

## Out of scope

- Org-wide erasure workflow (PRD §6). Metric TILE placement — **S22**.
