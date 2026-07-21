# S24 — L6 admin review queue: Accept / Reject (reuses S15 interaction pattern)

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T6 Agent-experience L6
- **Size:** M
- **Depends on:** S23
- **Delivers:** FR-24
- **Surface:** admin front end (L6 review queue) + BFF routes over the S22 store

## Goal

FR-24: "confirm gate UI: an admin review queue listing proposals with Accept /
Reject (reuses T3's proposal interaction pattern)." US23: the agent only
"learns" what a human approved.

## Approach

- Admin review queue over the S22 store, extending the minimal S22 list into
  the full queue; admin route group per ADR-0093 (§7 seam 7).
- Accept → `confirmed` with decider + timestamp; Reject → `rejected` — never
  applied anywhere.
- Reuses the S15 Accept/Dismiss interaction pattern (§7 seam 5: C2 and C8
  share the propose→confirm pattern); decider attribution is framework-derived.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** vitest: Accept/Reject → correct status transitions carrying
  decider + timestamp; rejected entries are excluded from any confirmed-entry
  read. Datastore integration (live Postgres): transitions persisted.
- **② E2E (browser):** the queue lists a pending proposal; Accept one and
  Reject another; both statuses visible with decider; screenshots.
- **③ Product (PAC):** PAC-7's confirm/reject legs (the "visibly applied"
  proof lands with S25's injection).

## Out of scope

- Injecting confirmed entries into turns — **S25**.
- Proposal generation — **S23**.
