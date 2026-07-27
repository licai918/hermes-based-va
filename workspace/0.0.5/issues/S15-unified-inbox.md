# S15 — Unified review inbox + Re-classify

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T4 Memory-ops UX
- **Size:** M
- **Depends on:** S02 (L7 queue), existing L6 queue
- **Delivers:** FR-22
- **Surface:** inbox page + merged queue read + Re-classify action

## Goal

FR-22: ONE queue holding every pending memory decision — L6 proposals, L7 proposals,
graduation items (S20), blast-radius reviews (S10), `persona_review` items (S25's routing) —
with layer badges, Accept/Edit/Reject, and **Re-classify** (move a mis-filed proposal to the
other layer's queue instead of reject-and-retype). L4 proposals stay in the copilot per-case
panel (reps in case context). Daily workflow: log in → inbox badge (N) → clear it. US9/US4.

## Approach

- Merged read over the pending sets (admin-only); item kinds are typed (l6_proposal,
  l7_proposal, graduation, blast_radius, persona_review) — later kinds land additively.
- Decisions dispatch to each layer's EXISTING governed decide actions (no new decision
  primitives); Re-classify = reject-in-source + propose-in-target in ONE governed action
  carrying provenance (audited both sides, evidence preserved).
- Inbox badge count on the hub + nav.
- S13 advisory annotations render inline where present.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** vitest — merged payload carries typed items with badges; each decision
  routes to the right governed action; Re-classify moves an L6→L7 item preserving evidence
  with both audit rows (live-PG); policy_blocked without actor.
- **② E2E (browser):** clear a mixed queue (accept one L6, reject one L7, re-classify one);
  badge count updates; screenshots.
- **③ Product (PAC):** PAC-5's inbox leg.

## Out of scope

- Triage annotations content — **S16**. New item kinds land with their slices (S10/S20/S25).
