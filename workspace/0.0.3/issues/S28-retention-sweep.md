# S28 — Retention sweep per ADR-0004/0116 classes + admin visibility (last run, per-class counts)

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T8 Hygiene
- **Size:** M
- **Depends on:** none
- **Delivers:** FR-30
- **Surface:** sweep job over `customer_memory_slot`; admin sweep-visibility entry

## Goal

FR-30: "a scheduled/manually-triggerable job aging out `customer_memory_slot`
rows per ADR-0004/0116 classes (provisional vs verified windows); sweep results
visible on an admin entry (last run, per-class counts)." US25: ADR-0004
compliance becomes observable.

## Approach

- Sweep job applying the ADR-0004/0116 retention classes (provisional vs
  verified windows); manually triggerable and schedulable — the scheduling
  mechanism is implementer's choice.
- Admin visibility entry (created here per NFR-1's entry rule): last run, rows
  aged/deleted per class.
- Sweep deletions recorded consistently with existing audit patterns.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** unit: class-window logic — seeded aged provisional rows
  selected, verified rows inside their window retained. Datastore integration
  (live Postgres): the sweep deletes exactly the aged rows and records
  per-class counts + last-run.
- **② E2E (browser):** seed old rows, trigger the sweep from the admin entry,
  see last-run + per-class counts update; screenshots before/after.
- **③ Product (PAC):** PAC-9's retention leg — "retention sweep demonstrably
  ages seeded old rows per class."

## Out of scope

- Connection pooling — **S29**.
- Org-wide erasure workflow — **out (§9 / T5 disposition)**.
