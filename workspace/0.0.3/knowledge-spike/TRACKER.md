# 0.0.3 Knowledge-layer spike — /triage board

**Direction D** (0.0.3 exploration): de-risk the knowledge layer (Candidate 1) with 3
hard-gate spikes BEFORE committing to a build, in parallel with the PAC-1 supervisor
view. This board tracks the **spike line only**. Plan → [SPIKE-PLAN.md](SPIKE-PLAN.md).

**Phase status:** `EXECUTING` — S-ISO ✅ + S-LAT ✅ passed (2026-07-16); corpus pulling from
Shopify; **S-QUAL blocked on the real question set** (see ⛔ below).

## Locked decisions (grill)
- Ladder: **Postgres FTS → small embedding → gbrain**; walk up only as far as S-QUAL needs.
- Pass bar: **recall@3 ≥ 80%** (gold chunk in top-3, ≥24/30).
- S-QUAL input: ~30 **real** SMS/support questions + gold labels from the product owner.

## Spikes (triage state)

| ID | Gate (pass/fail) | State | Verdict | Evidence |
| --- | --- | --- | --- | --- |
| **Scaffold + S-ISO** | index in a **separate DB** (`KNOWLEDGE_DATABASE_URL`); business datastore untouched; connections isolated | ✅ pass | ✅ pass | separate `toee_knowledge` DB + `knowledge_chunk`+GIN; biz `toee_va` unchanged (16 tbl), no leak; corpus ingested **27 docs → 167 chunks** (page 53 / article 66 / policy 48) |
| **S-LAT** | selected retriever in-turn **p95 < 800 ms** @ projected size **+** driver-side deadline → `found=false` | ✅ pass | ✅ pass | FTS **p95=1.40ms** @1500 (167 real+1333 synth); forced 2s query → found=false in 201ms |
| **S-QUAL** | **recall@3 ≥ 80%** on ~30 labelled real Qs; ladder FTS→embed→gbrain | 🔴 blocked (needs-info) | — | corpus ✓ (Shopify, ~20-28 real docs); ⛔ awaiting question set |
| **Decision gate** | Path X / Path Y / defer, from the above | ⚪ pending | — | waits on all 3 |

State legend: 🟢 ready · 🟡 in-progress · 🔴 blocked · ⚪ pending · ✅ pass · ❌ fail

## Decision gate (after all 3)
recall@3 ≥ 80% at the **lowest clearing rung** → FTS = **Path Y-FTS (M)** · embedding =
**Path Y-embed (M+)** · gbrain = **Path X (L)** · none clears → **defer** (0.0.3 falls back
to PAC-1 view + option D / judge tuning). S-LAT + S-ISO must both pass for *any* build.

## ⛔ Remaining input (gates S-QUAL only; scaffold + S-LAT + S-ISO proceed)
Company knowledge today ≈ empty (persona = 1 line, 6 policy slots empty, only Shopify product
is live-read). Corpus source **resolved** — Shopify-connector pull, confirmed viable (~15
pages + 5 policies + ~30 articles; 859 products excluded as live facts). **I produce it.**
The one input still needed from the product owner:
- **~30 real customer questions** (verbatim SMS/support phrasing) + gold page/topic per Q.

## Log
- (2026-07-16) Opened; direction D committed.
- (2026-07-16) Plan grilled (grill-with-docs) + locked: ladder, ≥80% bar, real-question
  input. `SPIKE-PLAN.md` written. Scaffold/S-LAT ready to execute; S-QUAL blocked on the
  question set.
- (2026-07-16) Corpus source = Shopify connector, confirmed viable (read-only probe:
  ~15 pages + 5 policies + ~30 articles; 859 products excluded as live facts).
- (2026-07-16) **S-ISO ✅** — separate `toee_knowledge` DB + `knowledge_chunk`+GIN stood up;
  business `toee_va` unchanged (16 tables), no `knowledge_chunk` leak. **S-LAT ✅** — FTS
  p95=0.82ms @1500 chunks (`probe/slat.py`); forced 2s query → `found=false` in 205ms via a
  200ms driver deadline. Corpus pull (subagent) → ingest → S-LAT reconfirm on real+padded next.
- (2026-07-16) Corpus ingested: `probe/corpus.json` (27 real Toee Tire docs) → **167 chunks**
  in `knowledge_chunk`. **S-LAT reconfirmed** on real+padded (p95=1.40ms). Table left real-only,
  **staged for S-QUAL** — only the ~30 questions remain. Scaffold + S-ISO + S-LAT ✅ done.
