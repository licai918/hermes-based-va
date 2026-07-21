# S16 — Proposal-history section on the supervisor view (dismissals visible)

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T3 Propose→confirm
- **Size:** S
- **Depends on:** S15, S20
- **Delivers:** FR-17 (surfacing)
- **Surface:** supervisor memory audit view (S20) + a read-only BFF history route

## Goal

FR-17's surfacing half (audit finding 14): "a dismissed proposal writes no
slot, so slot history alone cannot show it" — a proposal-history section on the
FR-20 supervisor view makes accepted **and** dismissed proposals visible with
proposal, origin, decider, and timestamp.

## Approach

- Proposal-history section added to the S20 supervisor view, reading the S15
  audit records.
- Read-only BFF route over the audit records; admin route group per ADR-0093.
- Ordering/pagination and per-customer scoping details are implementer's
  choice.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** vitest BFF: the history route returns both accepted and
  dismissed records with proposal/origin/decider/timestamp. Integration (live
  Postgres) against seeded accept + dismiss outcomes.
- **② E2E (browser):** on the supervisor view, a dismissed proposal appears in
  the history section with decider + timestamp while the slot list shows no
  trace of it; screenshot.
- **③ Product (PAC):** PAC-5's proposal-history leg (paired with PAC-3's
  dismiss case).

## Out of scope

- Writing the audit records — **S15**.
- The rest of the supervisor view (slots, write history, clear) — **S20**.
