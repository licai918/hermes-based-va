# S24 — Knowledge final gate (0.0.3 S32 fold-in): recall@3 ≥80% on the owner's real questions

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T6 Memory Control Loop — **OWNER INPUT REQUIRED**
- **Size:** S
- **Depends on:** owner's ~30 real customer questions (THE one external input of 0.0.5);
  soft: S05 (for the with/without-normalization synergy measurement — skip that measurement
  if S05 hasn't landed, don't block the gate)
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
  **MET 2026-07-30:** recall@3 = 17/21 = **81%** (bar 80%, exit 0); latency p95 = **11.54 ms**
  against the 800 ms budget plus the deadline-degrade leg, both PASS, exit 0.
- **② E2E (browser):** ask three of the real questions in the simulator → grounded answers
  citing the right content; screenshots.
  **RAN 2026-07-30, and it FAILED FIRST — which is the whole point of this leg.** The agent
  answered *"I don't have our return policy on hand to share here"* to a question the gate scored
  a HIT. Root-caused (D29) to L5 never being wired on the container stack: `KNOWLEDGE_BACKEND`
  absent from compose, `fastembed` undeclared, model not baked. Fixed; re-asked; the reply now
  carries the policy's real 7-day window and 15% restocking fee.
  Evidence: [`../knowledge-gate/S24-LIVE-ANSWER.md`](../knowledge-gate/S24-LIVE-ANSWER.md) —
  before/after in one thread, plus the in-container probe (tool payload 15 → 3894 chars).
  **Two questions were asked, not three, and no screenshot file was produced** (the text capture
  is verbatim from the live DOM). Both shortfalls stated rather than rounded up.
- **③ Product (PAC):** PAC-8 — the owner signs the gate report. **STILL OPEN, and not a
  formality:** this slice says *"Owner supplies the questions (+ expected source pages)"*. The
  owner supplied a real SMS transcript; the questions AND every expected source page were derived
  by the implementer. Until PAC-8 is signed, the bar FR-30 is measured against is the
  implementer's judgement, not the business's.

## Out of scope

- New retrieval architecture (the hybrid retriever stands). Corpus authoring beyond gap fixes.
