# S14 — Eval 24–26 → real path; add 27/28/29

- **Milestone:** 0.0.1 / M1
- **Size:** M
- **Depends on:** S03, S07, S09, S10
- **Delivers:** §6.3 eval, NFR-4
- **Surface:** `eval/`

## Goal

Move the ADR-0117/0118 memory assertions off the mock and add the missing
isolation / merge / adversarial scenarios.

## Files (likely)

- `eval/scenarios/24-customer-memory-explicit-upsert.yaml`
- `eval/scenarios/25-customer-memory-honor-injected.yaml`
- `eval/scenarios/26-customer-memory-no-inferred-write.yaml`
- new `eval/scenarios/27-customer-memory-isolation.yaml`
- new `eval/scenarios/28-customer-memory-merge-verified-wins.yaml`
- new `eval/scenarios/29-customer-memory-injection-inert.yaml`
- fixtures/assertions under `hermes/eval_runner/` as needed.

## Approach

- Repoint 24–26 to exercise the real datastore path (was mock-only).
- 27: two customers, isolation (maps R3 / PAC-5).
- 28: provisional→verified merge, verified value wins (maps R5b / PAC-3).
- 29: adversarial injected value does not alter behavior (maps FR-6 / RK-2).

## Acceptance

- Scenarios 24–29 green on the real path; wired into the launch eval run.

## Out of scope

- The engine changes they exercise (S03/S07/S09/S10).
