# S10 — Copilot identity-lookup swallow → PII-safe warning

- **Milestone:** 0.0.2 — memory governance
- **Size:** S
- **Depends on:** none
- **Delivers:** FR-8
- **Surface:** Copilot turn logging

## Goal

Make a swallowed Copilot case-memory identity-lookup failure **observable** via a
PII-safe `WARN` — parity with the S11 read-failure log.

## Problem

The `load_case_identity` branch in `_load_case_memory`
(`hermes-runtime/hermes_runtime/copilot_turn.py`, ~:191-215) swallows the failure
**silently**, so a broken lookup is invisible in the logs.

## Files (likely)

- `hermes-runtime/hermes_runtime/copilot_turn.py` — `_load_case_memory` /
  `load_case_identity` branch (~:191-215).
- parity reference: the S11 read-failure log already in `openrouter.py`.
- `copilot_turn` unit.

## Approach

Per FR-8, §6.3 FR-8 seam (S11-parity):

- Add a `WARN` on the swallow logging **binding_key + error type only — never
  PII** (no values, no customer data). Mirror the S11 read-failure log's shape.
  The turn still degrades cleanly (NFR-4 — no behaviour change to the degrade
  path).

## Acceptance

- Unit (§6.3 FR-8 seam): a forced identity-lookup failure emits the PII-safe
  warning (binding key + error type only, never PII); the turn still degrades
  cleanly.

## Out of scope

- Any behaviour change to the degrade path itself — unchanged (NFR-4).
