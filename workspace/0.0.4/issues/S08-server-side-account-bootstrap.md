# S08 — Server-side account bootstrap + lockout parity

- **Milestone:** 0.0.4 — durable substrate
- **Track:** T1 API-only workbench
- **Size:** S
- **Depends on:** none
- **Delivers:** FR-2
- **Surface:** datastore dev-bootstrap + accounts handler; workbench auth reads only

## Goal

FR-2: account seeding and lockout enforcement live only server-side, so S09
can delete the TS account store without losing the ADR-0018 policy or the dev
login story.

## Approach

- Datastore dev-bootstrap seeds rep/supervisor/admin dev accounts (existing
  `test_datastore_dev_bootstrap` seam); the workbench never hashes or seeds
  passwords again.
- **Parity check before deletion:** verify the datastore accounts handler
  enforces ADR-0018 (5 failed attempts → 15-min lockout, counters reset on
  success) exactly as `account-store.ts` does; port any gap with tests.
- Login/session BFF path confirmed to work end-to-end against the admin API
  only (it already has a ViaApi path — this slice proves parity, S09 removes
  the fallback).

## Acceptance — three-layer gate

- **① Technical:** handler tests for the lockout ladder; bootstrap test
  seeds and logs in via API path.
- **② E2E (browser):** login via the API path with a seeded account;
  lockout after 5 failures shown in UI; screenshots.
- **③ Product (PAC):** feeds PAC-1 (restart survival proven in S09/S10).

## Out of scope

- Deleting `account-store.ts` — **S09**. Production account provisioning
  workflows (dev seed only, as today).
