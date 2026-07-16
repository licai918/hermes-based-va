# S08 — Honored-leg fix + no-unprompted-recall (judge-wired, advisory)

- **Milestone:** 0.0.2 — memory governance
- **Size:** M
- **Depends on:** S06 (the judge)
- **Delivers:** FR-6, R5, R6
- **Surface:** eval runner + judge wiring

## Goal

Make the eval "honored" leg genuinely inspect the reply (via the S06 judge,
advisory) and add a no-unprompted-recall scenario — closing the PAC-2 gap.

## Problem

The honored leg is a **freebie**: `hermes/eval_runner/turn_result.py:72-74` forces
`honored_injected_preference=True` whenever a `memory_preset` exists, and
`hermes/eval_runner/assertions.py:198-209` always passes — so the suite stays
green even if the agent ignores every stored preference. And PAC-2 (no
over-recall) has **no eval leg at all** (flagged in the 0.0.1 sign-off).

## Files (likely)

- `hermes/eval_runner/turn_result.py:72-74` — remove the forced-`True`; call the
  S06 judge.
- `hermes/eval_runner/assertions.py:198-209` — the always-pass honored assertion.
- `eval/scenarios/` — a new no-unprompted-recall scenario.

## Approach

Per FR-6 / PRD §9, R5 / R6, advisory per NFR-3:

- Replace the honored leg's freebie with the **S06 judge's** honored verdict —
  recorded **advisory** (non-gating).
- Add a no-unprompted-recall scenario: a `memory_preset` is present, the customer
  says nothing memory-related, and the judge asserts the agent stays **silent**.

## Acceptance

- **R5** (§6.3 FR-6 seam, eval-unit): a transcript where the preference is
  ignored/re-asked no longer passes the honored leg — the freebie is gone.
- **R6**: a no-unprompted-recall scenario exists; its **advisory** judge signal
  (silence) is recorded.

## Out of scope

- The judge component itself — **S06**.
- The mechanical no-inferred hard gate — **S07**.
