# S15 — Unified review inbox + Re-classify

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T4 Memory-ops UX
- **Size:** M
- **Depends on:** S02 (L7 queue), existing L6 queue
- **Delivers:** FR-22
- **Surface:** inbox page + merged queue read + Re-classify action + **`review_item` store**

## ⚠ Pre-flight corrections — BINDING (see [../DECISIONS.md](../DECISIONS.md))

- **D1** — the `review_item` migration is allocated prefix **0022**. Re-verify by listing the
  migrations directory before writing yours.
- **D8** — `review_item` also gets the `annotations` JSONB column (same shape as S13/S16's
  proposal-row column: reserved top-level keys `heuristic` and `copilot`). S16 annotates
  graduation, blast-radius, and persona_review items too, and those live only in `review_item`
  — without this column S16's scope silently shrinks to the two proposal tables, contradicting
  FR-23.
- **D9** — the `kind` enum below is corrected to six values: `l6_proposal, l7_proposal,
  graduation, blast_radius, persona_review, retirement_candidate`. S20 emits the
  `retirement_candidate` kind and the enum as written here doesn't contain it.
- **D17** — you are the third of five serialized catalog-touching slices (S01 → S02 → S15 → S11
  → S10). Confirm S02 has landed before you touch the shared nine-file sync set, and leave it
  clear for S11 next.

## Goal

FR-22: ONE queue holding every pending memory decision — L6 proposals, L7 proposals,
graduation items (S20), blast-radius reviews (S10), `persona_review` items (S25's routing) —
with layer badges, Accept/Edit/Reject, and **Re-classify** (move a mis-filed proposal to the
other layer's queue instead of reject-and-retype). L4 proposals stay in the copilot per-case
panel (reps in case context). Daily workflow: log in → inbox badge (N) → clear it. US9/US4.

## Approach

- **`review_item` store (gap-audit fix — the non-proposal kinds need a home):** L6/L7
  proposals live in their own tables, but graduation (S20), blast-radius (S10), and
  persona_review (S25) items do NOT — this slice ships a small `review_item` table
  (migration: id, kind, subject_ref, evidence JSONB, status open|acknowledged|dismissed,
  decider, timestamps) that those slices emit into. Emission is propose-only; deciding an
  item is audited.
- Merged read over the pending sets (proposal tables + `review_item`, admin-only); item kinds
  are typed (l6_proposal, l7_proposal, graduation, blast_radius, persona_review) — later
  kinds land additively.
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
