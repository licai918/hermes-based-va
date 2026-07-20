# S08 — Hybrid retriever: FTS + local embedding (fastembed) + RRF fusion, top-k with provenance

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T1 Knowledge layer L5
- **Size:** M
- **Depends on:** S07
- **Delivers:** FR-3
- **Surface:** retrieval module over the knowledge store; no driver/turn wiring

## Goal

FR-3: "hybrid retriever: lexical FTS + dense embedding (local model via
fastembed/onnx — no torch, no per-call cost, queries stay local) fused by
reciprocal-rank; returns top-k chunks with title+url provenance." Spike rung 2
(embedding, 73% synthetic) is the evidence base for Path Y-embed.

## Approach

- FTS query + embedding-similarity query over `knowledge_chunk`; RRF fusion;
  top-k results each carrying title+url provenance.
- Embedding model is local (fastembed/onnx) and the same model the S07
  ingestion used — no torch, no per-call cost, queries never leave the machine.
- Fusion weights and chunking stay tunable — S12's harness and S32's
  tune-then-sign loop adjust them; defaults are implementer's choice.
- Pure retrieval module: governance, gating, and deadline are S09; turn wiring
  is S10.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** unit (hermes/tests seam): RRF fusion ordering on fixtures;
  provenance present on every result; empty-result path clean. Integration
  (live Postgres): a hybrid query over the real ingested corpus returns fused
  top-k with provenance.
- **② E2E (browser):** a minimal retrieval probe on the existing
  `/admin/knowledge` surface (query in → top-k + provenance out) — created here
  per NFR-1's entry rule since no nearer front-end entry exists yet; placement
  is implementer's choice; screenshot.
- **③ Product (PAC):** feeds PAC-1 and PAC-10 (via S12/S32).

## Out of scope

- Governed driver, `knowledge_enabled()`, deadline — **S09**.
- Recall@3 + hybrid p95 harness — **S12**.
