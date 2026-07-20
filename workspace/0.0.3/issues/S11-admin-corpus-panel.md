# S11 — Admin knowledge corpus panel

> **Scope addition (2026-07-20, from S08's review):** this slice ALSO delivers the
> **retrieval probe** — a small "test a query" form on the admin knowledge surface that
> calls `toee_knowledge_search.search_public_site` through the admin dispatch (hitting the
> REAL S09 driver + S08 retriever) and renders the top-k chunks with provenance. It is
> S08's re-scoped layer-② evidence as well as this panel's.: status (docs/chunks/last-ingest) + re-ingest action

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T1 Knowledge layer L5
- **Size:** M
- **Depends on:** S07
- **Delivers:** FR-6
- **Surface:** admin front end (`/admin/knowledge` or a sibling) + BFF status/re-ingest routes

## Goal

FR-6: "admin knowledge entry (front-end): corpus status (doc/chunk counts, last
ingest time, per-type breakdown) + a re-ingest action, on the existing
`/admin/knowledge` surface or a sibling." US22: knowledge refresh becomes an
explicit, visible operation.

## Approach

- BFF status route reads docs/chunks/last-ingest/per-type from the knowledge
  DB; panel renders it on the existing `/admin/knowledge` surface or a sibling
  (implementer's choice per FR-6).
- Re-ingest action triggers the S07 job; the run's boundary-check outcome
  (flagged-item count, at minimum) is surfaced — detail level implementer's
  choice.
- Admin route group + role gating per ADR-0093 (§7 seam 7).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** vitest BFF route tests: status payload shape (docs, chunks,
  last-ingest, per-type); re-ingest action dispatches the job. Integration:
  counts match the live corpus after an ingest run.
- **② E2E (browser):** open the panel; doc/chunk counts + last-ingest visible;
  click re-ingest; counts/timestamp refresh after the run; screenshots
  before/after.
- **③ Product (PAC):** feeds PAC-1; owner uses re-ingest during S32's content
  fills (US22 sign-off at S33).

## Out of scope

- Recall/latency reports on the admin eval surface — **S12**.
- Ingestion pipeline internals + boundary-check rules — **S07**.
