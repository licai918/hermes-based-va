# 0.0.3 Knowledge-layer feasibility — SPIKE PLAN

**Direction D.** Decide **Path Y (in-house) vs gbrain (Path X) vs defer** with data,
before committing a build. These are throwaway probes; the seam + schema they leave
behind are the real build's foundation (not pure throwaway — see last section).

Tracks with [TRACKER.md](TRACKER.md). Source: [../EXPLORATION.md](../EXPLORATION.md)
Candidate 1; spec §M2
([design](../../../docs/superpowers/specs/2026-07-10-memory-architecture-activation-design.md)).

---

## Decisions locked (grill-with-docs, 2026-07-16)

1. **Retrieval ladder** — `Postgres FTS → small embedding → gbrain`. Walk **up only as
   far as S-QUAL needs**. Reverses 0.0.1's gbrain lean; FTS is zero-dependency.
2. **S-QUAL input** — ~30 **real** customer questions from SMS/support logs, each with
   its **gold page/chunk labelled by the product owner**. → **[BLOCKING INPUT, see below]**
3. **Pass bar** — **recall@3 ≥ 80%** (gold chunk in top-3 for **≥ 24 / 30**).

## Grounding (current state, verified — Explore fact sheet)

- Knowledge read = **2-entry hard-coded mock** (`drivers/mock/knowledge.py:39`).
  gbrain / pgvector / BM25 / RAG / crawl = **0 lines of code** (spec §M2, planned only).
- `extra_drivers` injection seam is **live + proven** (Customer Memory ships on it,
  `tool_backend.py:82` `_customer_memory_extra_drivers`). A retriever driver is a
  drop-in copy behind a new `knowledge_enabled()` twin of `memory_enabled()`.
- **NO timeout on tool dispatch** (`execute.py:112`, sync `driver.execute`, no deadline)
  → a slow retriever blocks the whole SMS turn. **The deadline is the spike's job.**
- **NO** pgvector (stock `postgres:16`), **NO** embedding/vector dep anywhere, **NO**
  second-DSN seam, **NO** `brain/` corpus, **NO** latency instrumentation. All greenfield.

## Key framing

For **Path Y** the cheapest retriever is **Postgres full-text search** (`tsvector` /
`ts_rank`, no new dependency, no pgvector, no external service). Under that,
**S-LAT and S-ISO are near-certain passes** (FTS in a separate DB is a known quantity).
**The only spike that can genuinely fail is S-QUAL** — can keyword retrieval hit the
right chunk for real, often-paraphrased customer questions? Effort concentrates there.

---

## The scaffold (prerequisite for all three — stand up first)

1. **Separate DB** via a new `KNOWLEDGE_DATABASE_URL` env var; lazy DSN resolution
   mirroring `PostgresDriver` (`tool_backend.py:72`). (This *is* the S-ISO substrate.)
2. **`knowledge_chunk` table** in that DB: `(id, page_id, page_type, title, url,
   chunk_text, tsv tsvector)`, GIN index on `tsv`. No PII, ever.
3. **Seed `brain/` corpus (~15–25 pages)** — I derive from existing toeetire.com pages
   + `persona.py` + plain-language restatements of the 6 policy slots (NOT verbatim
   policy copy — boundary respected). Chunk → insert. *Kept if the product owner
   approves the content.*
4. **`BrainRetrieverDriver` skeleton** — `query → ts_rank top-k → {found, chunks[]}`,
   injected via `extra_drivers` behind `knowledge_enabled()`. Governed `found=false` on
   miss (existing degradation path).

---

## S-ISO — separate-DB isolation

- **Gate:** `knowledge_chunk` reachable via `KNOWLEDGE_DATABASE_URL`; business
  `database_url()` **untouched** (no new tables/cols there); the two connections never
  cross.
- **Method:** bring up a 2nd DB (compose service, or a 2nd database in the same
  instance per spec §M2); run the scaffold against it; assert business migrations/schema
  unchanged (`git diff` on the runtime schema = empty).
- **Verdict shape:** near-certain pass. Fails only if a separate DSN can't be wired.

## S-LAT — in-turn latency + the deadline mechanism

- **Gate (two parts):** (a) the **selected** retriever's in-turn **p95 < 800 ms** at a
  **projected corpus size** (~500–2000 chunks; pad the seed with synthetic filler so the
  number is meaningful, not the ~10 ms a 25-page corpus gives); **and** (b) a
  **driver-side deadline fires → governed `found=false`** on overrun — the turn never
  blocks.
- **Method:** throwaway timing harness (`perf_counter` around `driver.execute`) × N
  synthetic queries at padded size → p95. Then force a slow query (`pg_sleep`) and assert
  the deadline path returns `found=false`, not a hang.
- **Measured for the rung S-QUAL selects** (FTS first — it's the substrate and the
  likely winner). If S-QUAL escalates to embedding, re-run S-LAT for that rung.
- **Verdict shape:** FTS/embedding near-certain on latency; **the deadline wiring is the
  real deliverable** (it's the actual production risk, given no tool timeout exists).

## S-QUAL — retrieval quality (the linchpin) — [gated on the question set]

- **Gate:** **recall@3 ≥ 80%** (gold chunk in top-3 for ≥ 24 / 30 real questions).
- **Measured OFFLINE** (no latency constraint here — latency is S-LAT's job), walking
  the ladder, stopping at the lowest rung that clears the bar:

  | Rung | Retriever | If ≥ 80% | If < 80% |
  | --- | --- | --- | --- |
  | 1 | **Postgres FTS** (`ts_rank`) | **Path Y-FTS ships**, gbrain deferred | 60–80% → tune (stemming, synonym dict, title-boost) + re-measure; still short → rung 2 |
  | 2 | **Small embedding** (compact model → in-Python cosine over the seed; throwaway, no pgvector) | **Path Y-embed ships** (one dep, no external service) | → rung 3 |
  | 3 | **gbrain** (Path X spike) | **Path X justified** (accept external-service + pgvector cost) | **DEFER** the knowledge layer this iteration (retrieval not good enough; revisit corpus/approach) |

- **Inputs:** the product owner's 30 questions + gold labels; the seed corpus.

---

## Decision gate (what the results feed)

- **recall@3 ≥ 80% at the lowest clearing rung** picks the build:
  - FTS → **Path Y v1 (M)** — real chunker/index/authoring/ADR.
  - embedding → **Path Y v1 + one embedding dep (M+)**.
  - gbrain → **Path X (L)** — deploy + isolate + read-scoped credential.
  - **nothing clears** → **DEFER**; 0.0.3 headline falls back to the PAC-1 supervisor
    view + option D / judge tuning.
- **S-LAT + S-ISO must both pass for ANY build** — they gate *viability*, not *path*.

## Sequencing

1. **Scaffold + S-ISO** — now (no labelled set needed).
2. **S-LAT (FTS)** — now (synthetic queries + the deadline wiring).
3. **S-QUAL** — when the question set lands; walk the ladder; re-run S-LAT if it escalates.

Est: scaffold + S-ISO + S-LAT ≈ **1 day**; S-QUAL ≈ **0.5–1 day** once questions arrive.

## Throwaway vs kept

- **Kept** (real-build foundation): the DSN seam, `BrainRetrieverDriver` skeleton,
  `knowledge_chunk` schema, the deadline→`found=false` wiring, the seed corpus (if
  approved).
- **Thrown:** the timing harness, synthetic padding, and any losing per-rung tuning.

---

## ⛔ Blocking input (needed before S-QUAL runs)

**~30 real customer questions** drawn from actual SMS / support history — verbatim
customer phrasing (paraphrase and colloquialism are the point) — and for each, the
**gold answer** (which page/topic *should* be retrieved). Scaffold + S-LAT + S-ISO
proceed without it; **S-QUAL blocks on it.**
