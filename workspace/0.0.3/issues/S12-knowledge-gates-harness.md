# S12 — Gates harness: recall@3 runner + hybrid in-turn p95 re-run (FR-7b); reports on admin; knowledge ADR

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T1 Knowledge layer L5
- **Size:** M
- **Depends on:** S08, S09
- **Delivers:** FR-7, FR-7b, NFR-8 (knowledge ADR)
- **Surface:** harness commands; admin eval/metrics entry (reports); ADR docs

## Goal

FR-7: a labelled-question runner reporting recall@3, repeatable on demand,
running the synthetic set during dev (the real-question final gate is S32).
FR-7b: "measure the **hybrid retriever's** in-turn p95 — *including per-query
embedding inference* — at projected corpus size; gate p95 < 800 ms, and verify
the FR-4 deadline still degrades correctly around the slower path." Ships the
**knowledge ADR** (NFR-8).

## Approach

- Recall@3 runner as a repeatable command (US27); synthetic set during dev.
- **FR-7b carries audit finding 1:** the spike's S-LAT measured the rejected
  FTS rung only and the escalation rule "re-run S-LAT for the selected rung"
  was never executed — re-run it for the hybrid rung, embedding inference
  included, at projected corpus size; gate p95 < 800 ms; re-verify the S09
  deadline degrade around the slower path.
- Both the recall report and the latency report surface on the admin
  eval/metrics entry so the gates are front-end-visible (the FR-29 judge report
  joins at S27); create the eval entry if it does not exist yet.
- **Knowledge ADR:** records Path Y-embed hybrid, formally supersedes
  ADR-0001/0031's mechanisms, and carries the authoring/review-gate open
  question from FR-2 (NFR-8).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** the recall runner reports recall@3 on the synthetic set as
  a repeatable command; the latency runner reports hybrid in-turn p95 < 800 ms
  with embedding inference included; the deadline-degrade check passes against
  the hybrid path. Knowledge ADR present in the build.
- **② E2E (browser):** recall + latency reports visible on the admin eval
  entry (NFR-1: dev-harness outputs satisfy ② via the panel that surfaces
  them); screenshot.
- **③ Product (PAC):** feeds PAC-1 and PAC-10 (the final real-question gate is
  S32).

## Out of scope

- The ≥80% real-question gate + tuning loop — **S32**.
- Judge fixture set / report — **S27**.
