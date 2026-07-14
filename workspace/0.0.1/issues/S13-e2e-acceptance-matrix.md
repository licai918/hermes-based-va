# S13 — E2E acceptance: matrix + isolation + merge + tripwire + degradation

- **Milestone:** 0.0.1 / M1
- **Size:** L
- **Depends on:** S04–S11
- **Delivers:** §6.1 layer matrix, §6.0 principles, §6.6 technical gate
- **Surface:** `hermes-runtime/tests/` E2E

## Goal

One end-to-end suite that proves all four memory layers are live in a real turn,
content and customer are correct, and the activation cannot silently revert.

## Files (likely)

- New E2E test module driving the simulated Textline webhook → real Postgres,
  using the existing scripted OpenAI provider (`_scripted_openai_factory`) so the
  turn is deterministic and can assert on the injected user message.

## Coverage

- **§6.1 matrix:** one run asserts L1 (binding key), L2 (thread/session/turn/
  agent_turn_context rows), L3 (case + audit rows), L4 (slot row + value appears in
  round-2 injection).
- **Isolation (R3/PAC-5):** two phones; each sees only its own memory.
- **Merge chain (R5):** unmatched states preference → verify → honored under
  verified id.
- **Dormancy tripwire (§6.0.4):** same E2E with the composite driver disabled must
  **fail** (write lands in mock, injection empty).
- **Degradation (FR-7):** no-DB turn completes and replies, no artifact.
- **Anti-mock:** live-turn writes show `driver.kind = "datastore"`; 0 reach mock.

## Acceptance

- All above green (tripwire confirmed red-when-disabled); pasted output for the
  §6.6 technical gate.

## Out of scope

- Model-quality/behavior judgments — those are eval (S14) and product UAT (S15).
