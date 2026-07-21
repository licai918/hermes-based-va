# S25 — CI harness topology (full stack in CI)

- **Milestone:** 0.0.4 — land all seven
- **Track:** T6 Eval completion (infra enabler; added by gap review, hence
  out-of-order numbering — S24 remains the final gate)
- **Size:** M
- **Depends on:** S10 (orchestration to reuse)
- **Delivers:** NFR-9
- **Surface:** CI workflow + compose profile; no product code

## Goal

NFR-9 (gap-review fix Q1): the scripted-mode live-eval suites need a real
turn path in CI — gateway + both dispatch servers + turn worker + Postgres.
Today's CI (0.0.3 S30) provisions Postgres only. This slice owns that lift
explicitly so S18/S19 don't smuggle CI infra inside an eval slice.

## Approach

- Reuse the S10 orchestration (compose services + readiness waits) in a CI
  profile: Postgres (+ knowledge DB), both dispatch servers with
  `scripted_completions` seeded, gateway with `REPLY_SENDER=simulated`,
  turn worker. Background worker only if a suite needs it.
- Keep the job deterministic: scripted completions only; no OpenRouter key
  in this job (the live-model job is S20's, non-required).
- Cache/boot budget: document CI wall-time before/after; keep the harness
  job parallel to the existing unit/replay jobs.

## Acceptance — three-layer gate (pure-infra carve-out)

- **① Technical:** a CI run boots the full topology and executes an S18
  scripted harness smoke (2 scenarios) green twice consecutively
  (determinism proof); teardown leaves no orphan services.
- **② E2E:** CI run page showing the harness job green; screenshot.
- **③ Product (PAC):** infrastructure — feeds PAC-8 via S18/S19.

## Out of scope

- The harness itself — **S18**. Suite recording — **S19**. Live-model job —
  **S20**.
