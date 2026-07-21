# S32 — Knowledge final gate: recall@3 ≥ 80% on the ~30 real questions (tune-then-sign loop)

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T1 Knowledge layer L5 — final gate
- **Size:** S
- **Depends on:** S12 (+ the owner's ~30 real questions)
- **Delivers:** FR-7 (final gate), PAC-10
- **Surface:** S12 harness run over the real-question set; retriever/chunking tuning knobs; admin eval report

## Goal

FR-7's final gate: "**final gate = recall@3 ≥ 80% on the ~30 owner-supplied
real questions** (PAC-10); if it misses, tune (fusion weights, chunking, model)
and re-run before sign-off." RK-1's tune-then-sign loop is budgeted; only this
gate blocks on owner inputs (RK-2).

## Approach

- Run the S12 recall harness on the owner-supplied real-question set.
- On a miss, tune and re-run: fusion weights, chunking, short-doc handling,
  model choice (RK-1); worst case this PAC extends past the other tracks.
- Content gaps cap achievable recall — hours/FAQ/payment are unanswerable
  until the owner fills them (RK-2, CONTENT-GAPS.md); re-ingest via S11 after
  fills, then re-run.
- The passing run's report lands on the admin eval entry with the S12 reports.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** the harness reports recall@3 ≥ 80% on the real-question set
  as a repeatable command; the run configuration (weights/chunking/model) that
  passed is recorded.
- **② E2E (browser):** the real-question recall report showing ≥ 80% visible
  on the admin eval entry (dev-harness output surfaced per NFR-1); screenshot.
- **③ Product (PAC):** PAC-10 — the owner signs the knowledge gate
  (tune-then-sign if missed).

## Out of scope

- The harness itself — **S12**; ingestion/panel — **S07/S11**.
- Full product UAT + sign-off doc — **S33**.
