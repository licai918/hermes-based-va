# S24 — Knowledge final gate (0.0.3 S32 fold-in): recall@3 ≥80% on the owner's real questions

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T6 Memory Control Loop — **OWNER INPUT REQUIRED**
- **Size:** S
- **Depends on:** owner's ~30 real customer questions (THE one external input of 0.0.5)
- **Delivers:** FR-30
- **Surface:** knowledge gates harness (exists); question set; possibly Shopify content fixes

## Goal

FR-30 (owner decision ⑥): close the oldest open debt — the L5 knowledge layer's REAL quality
gate. The synthetic interim gate measured recall@3 = 73%; the real gate runs the owner's ~30
actual customer questions through `hermes_runtime.knowledge.gates recall` and must clear
**recall@3 ≥ 80%**. US20.

## Approach

- Owner supplies the questions (+ expected source pages); encode them as the gate's question
  set (replacing/alongside the synthetic set, both kept for trend).
- Misses get diagnosed the established way: content gap → edit Shopify + re-ingest
  (CONTENT-GAPS.md flow); retrieval gap → tuning within existing knobs (chunking/weights);
  NORMALIZATION gap → S05's lexicon seam should already lift digit-string queries (measure
  with/without to show the L7 synergy).
- If the bar cannot be met after content fixes, the honest outcome is a documented
  gap-analysis + owner decision — never a silently lowered bar.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** `gates recall` ≥80% on the real set, output archived as the gate artifact;
  latency gate re-run green at the current corpus size.
- **② E2E (browser):** ask three of the real questions in the simulator → grounded answers
  citing the right content; screenshots.
- **③ Product (PAC):** PAC-8 — the owner signs the gate report.

## Out of scope

- New retrieval architecture (the hybrid retriever stands). Corpus authoring beyond gap fixes.
