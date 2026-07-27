# S25 — Feedback aggregator: one scheduled propose-only job (N=3/M=3, routing table)

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T6 Memory Control Loop
- **Size:** M
- **Depends on:** qf Phase 1 merged (tables 0018/0019); S01; S15
- **Delivers:** FR-32
- **Surface:** scheduled background job; inbox item emission

## Goal

FR-32 (C6 §§6.2-6.3): ONE background-worker job reads both feedback tables since the
watermark, clusters (tag × subject × correlation id), and when a threshold trips —
**N=3 same-tag fails / M=3 similar edit-diffs** (grill-locked starting values) — emits
`proposed` rows into the EXISTING queues per the Signal Routing Table (L6 `feedback_derived`
proposals, L7 proposals, knowledge-slot drafts, `persona_review` inbox items for
out-of-memory signals). Nothing auto-writes memory — propose→confirm absolute. US18.

## Approach

- Job skeleton = the 0.0.4 S22 honored-rate job pattern (worker + watermark + aggregate);
  proposals carry the feedback row ids as evidence; source `feedback_derived` distinguishes
  them in every queue.
- Implement the routing table EXACTLY as pinned in C6 §6.2 (including the OUT-of-memory rows:
  tone/persona → `persona_review` item; policy → the existing KnowledgeOps flow).
- Thresholds are named constants on the knob panel (S22); weight implicit outcomes vs explicit
  ratings per the qf-PRD volume note.
- Eval-neutral by construction (proposed rows are inert; the only turn-reaching path is
  confirmed entries, already pinned).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** live-PG — seed 3 same-tag fails on similar subjects → exactly ONE
  evidence-linked proposal in the right queue (idempotent re-runs); 2 fails → nothing; a
  tone-tagged cluster → a persona_review item; job failure leaves queues clean; replay green.
- **② E2E (browser):** seeded feedback → the proposal appears in the inbox with evidence
  links; screenshot.
- **③ Product (PAC):** PAC-7's front half.

## Out of scope

- Edit-diff MINING (the M-threshold's diff clustering) — **S27** (this slice lands the
  tag-cluster arm; the diff arm's threshold plumbing is shared). Loop metrics — **S28**.
