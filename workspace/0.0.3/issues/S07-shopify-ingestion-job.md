# S07 — Shopify-connector ingestion job (pull→chunk→embed→index, idempotent, boundary-check report)

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T1 Knowledge layer L5
- **Size:** M
- **Depends on:** S06
- **Delivers:** FR-2, NFR-3
- **Surface:** ingestion job (repeatable command); Shopify connector read path; knowledge store writes

## Goal

FR-2: "a repeatable job pulling pages / blog articles / shop policies from the
Shopify connector (read-only; products/orders/PII excluded), HTML→text, chunk,
embed, index. Idempotent re-ingest (truncate-and-reload is acceptable at this
corpus size)." This slice also carries the **boundary-check report** (audit
finding 3).

## Approach

- Repeatable command (US27 harness discipline); source pinned to the Shopify
  connector per the spike's corpus decision.
- Pipeline: pull → HTML→text → chunk → embed (the local fastembed model shared
  with S08) → index into `knowledge_chunk`.
- Read-only against Shopify; products/orders/PII excluded at the pull level
  (NFR-3: the knowledge DB carries no customer data).
- **Boundary check at ingest:** content that verbatim-duplicates a governed
  operational-policy slot, or embeds live-fact patterns (prices/stock), is
  flagged into a human-review report — not silently indexed — enforcing the L5
  boundaries table. Report format/location is implementer's choice.
- Authoring/review-gate governance beyond this lint (who edits Shopify vs who
  reviews) is an **open question carried to the knowledge ADR (S12)**, not
  decided here.
- Idempotency: re-running produces the same corpus (truncate-and-reload).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** unit: chunking + boundary-flag rules on fixture content —
  flagged items appear in the report and not in the index. Integration (live
  Postgres): an ingest run populates chunks + FTS; a re-run is idempotent.
- **② E2E (browser):** after an ingest run, the `/admin/knowledge` entry shows
  the corpus present; screenshot. (Full status panel is S11.)
- **③ Product (PAC):** feeds PAC-1; the owner reviews the boundary report as
  part of S32/S33.

## Out of scope

- Retrieval — **S08**; status panel + re-ingest button — **S11**.
- Recall gate + knowledge ADR — **S12**.
