# S20 — Supervisor memory audit view: slots + write history (source/actor/time) + attributed clear

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T5 Transparency & control
- **Size:** M
- **Depends on:** none
- **Delivers:** FR-20
- **Surface:** admin front end (new supervisor view) + read BFF route; governed clear dispatch

## Goal

FR-20: "supervisor memory audit view (admin surface): per-customer slots + full
write history (`source`, `actor_account_id`, timestamps), with an attributed
**clear** action. Closes the 0.0.2 PAC-1 caveat (the data shipped in 0.0.2;
this is the UI + read BFF route)." US20/21: "who changed this" answerable in
the UI, not SQL; deletion requests honorable end-to-end.

## Approach

- **Build on the shipped model** (audit finding 7): slot metadata + the
  merge-audit table + structured logs — no schema change; the 0.0.2 §6.4
  audit-model wording divergence stays on record, accepted as-is.
- Read BFF route: per-customer slots + full write history with source, actor,
  timestamps; admin route group per ADR-0093 (§7 seam 7).
- Clear action routes through the existing governed dispatch path, attributed
  and audited — no new write path.
- Per the T5 disposition (audit finding 2): this view + S21 self-service
  **are** the v1 memory-deletion mechanism; org-wide erasure wiring is out of
  scope (§9).
- The proposal-history section joins this view in S16.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** vitest BFF: history payload carries source/actor/timestamps
  for UI-, draft-, and merge-written rows; datastore integration (live
  Postgres): clear removes slots and persists an attributed audit entry.
- **② E2E (browser):** open the view for a simulated customer (this slice
  CREATES the entry): "who wrote this slot, when, from where" is answerable on
  screen; clear a slot → history shows the attributed clear; screenshots.
- **③ Product (PAC):** PAC-5 — the owner verifies attribution for UI-, draft-,
  and merge-written rows and that clear works and is audited.

## Out of scope

- Proposal-history section — **S16**.
- Customer-facing self-service — **S21**.
