# S30 — CI provisions Postgres — datastore/E2E gate runs in CI

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T8 Hygiene
- **Size:** S
- **Depends on:** none
- **Delivers:** NFR-7
- **Surface:** CI pipeline (Postgres service + datastore/E2E gate); no product code

## Goal

NFR-7: "CI provisions Postgres so the datastore/E2E acceptance gate runs in
CI (closes the 0.0.1 debt)." US28: the suites that today require a local live
Postgres become a real CI gate instead of a skipped one.

## Approach

- CI provisions a Postgres service; the datastore/E2E suites
  (hermes-runtime/tests) run against it as a required gate, no longer skipped.
- Migrations applied in CI for the business DB and (once S06 lands) the
  `toee_knowledge` DB; mechanism is implementer's choice.
- Local-first posture unchanged (ADR-0142) — CI Postgres is the only infra
  change this iteration (§9).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** the datastore/E2E gate executes and passes in CI (visibly
  not skipped); a deliberately broken datastore test fails the pipeline
  (proving the gate bites), then is reverted.
- **② E2E (browser):** the CI run page showing the datastore/E2E job green as
  a required check; screenshot.
- **③ Product (PAC):** infrastructure slice — feeds the overall gate at S33
  (no direct owner scenario).

## Out of scope

- Connection pooling — **S29**.
- Any deployment/cloud change — **out (§9)**.
