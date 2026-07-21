# Hybrid lexical+embedding Knowledge retriever, separate-DB isolation, and the quality/latency gates

> **Status: Accepted — implemented** (decided during the 0.0.3 knowledge spike,
> formalized 2026-07-20). Formally supersedes the **implementation
> mechanisms** of [ADR-0001](0001-hybrid-knowledge-weekly-local-rag.md) and
> [ADR-0031](0031-shopify-primary-knowledge-sync.md) — see "What this
> supersedes" below. Ships on `feat/0.0.3-land-all`: S06–S12.

## Context

ADR-0001 and ADR-0031 committed the L5 Knowledge layer to a weekly-scheduled
Hermes Skill (**Knowledge Crawl** / **Shopify Knowledge Sync** + **Tavily Gap
Crawl**) writing into **Hermes Native Memory**, with no vector database. None
of that mechanism was ever built. The 0.0.3 PRD (FR-1..FR-9, NFR-8) reopened
the retrieval-mechanism question and ran a spike
([`workspace/0.0.3/knowledge-spike/`](../../workspace/0.0.3/knowledge-spike/),
`SPIKE-PLAN.md` Candidate 1 of
[`workspace/0.0.3/EXPLORATION.md`](../../workspace/0.0.3/EXPLORATION.md))
before committing engineering effort, gated on three questions: isolation
(does a knowledge store touch the business DB?), latency (can retrieval fit
inside a turn?), and quality (does retrieval actually find the right chunk?).

Two retrieval paths were evaluated:

- **Path X — gbrain**: a general-purpose external knowledge/graph service.
  Rejected as over-engineering for a curated, FAQ-sized corpus (167 chunks at
  spike time) — it adds an operational dependency (a second service to run,
  monitor, and version) to solve a problem an in-process retriever solves in a
  few hundred lines, with no clustering, sharding, or multi-tenant need in
  sight for this corpus size.
- **Path Y — embed, in-house hybrid**: Postgres full-text search (lexical) +
  in-process cosine similarity over `fastembed`-produced dense embeddings
  (semantic), fused by Reciprocal Rank Fusion. Chosen.

S06–S11 built Path Y (schema, ingestion, retriever, driver+deadline, turn
wiring, admin corpus panel). This ADR (S12) is the formal decision record and
ships alongside the **productionized quality/latency gate harness**
(`hermes_runtime/knowledge/gates.py`) that FR-7/FR-7b require, closing the
audit finding that the spike's own S-LAT probe measured the *wrong* rung.

## Decision

### 1. Path Y-embed hybrid retrieval (gbrain/Path X rejected)

`hermes_runtime/knowledge/retriever.py`'s `retrieve()` fuses two independent
rankings over `knowledge_chunk` by RRF (k=60):

- **Lexical**: Postgres `tsv @@ to_tsquery(...)` / `ts_rank`, with lexemes
  OR'd (not AND'd) — the spike's `squal.py` finding that `plainto_tsquery`'s
  implicit AND fails most multi-word natural-language questions.
- **Semantic**: cosine similarity between the query embedding
  (`BAAI/bge-small-en-v1.5`, 384-dim, via `fastembed`, asymmetric
  `query_embed`) and every chunk's stored embedding, held in-process (167×384
  floats is trivial; no pgvector needed at this corpus size).

gbrain (Path X) is rejected: no service to operate, no data-plane hop, no
additional attack surface, for a corpus this repo's own content volume will
not outgrow soon. If the corpus grows by an order of magnitude and quality or
latency degrades, gbrain (or pgvector) is the next escalation — not decided
here, not needed yet.

### 2. Separate-database isolation (S-ISO)

Knowledge lives in its own Postgres database, `toee_knowledge`, never inside
the business datastore (`toee_va`). `hermes_runtime/knowledge/config.py`'s
`knowledge_database_url()` has its own DSN env var
(`KNOWLEDGE_DATABASE_URL`), independent of `hermes_runtime.datastore`'s
`database_url()`, and no code path shares a connection between them. This is
deliberate: L5 Knowledge is a shared, non-PII corpus (company/product
content); the business datastore holds customer PII and transactional state.
Keeping them physically separate makes "knowledge queries can never touch
customer data" a structural fact, not a code-review discipline.

### 3. The driver-side deadline is required (FR-4, NFR-5)

There is no in-repo tool-call timeout mechanism, so `KnowledgeDriver`
(`hermes_runtime/knowledge/driver.py`) enforces its own: the whole retrieval
call (SQL + query-embedding inference) runs in a bounded worker thread
(`KNOWLEDGE_RETRIEVAL_DEADLINE_MS`, default 800ms); a timeout or any retriever
exception degrades to the governed no-match shape (`{"results": []}`) and
never raises, never hangs the turn. This is not optional belt-and-braces — the
spike proved the naive path (no deadline) has no other backstop.

### 4. FR-7/FR-7b gates, productionized (S12, this slice)

The spike's probes (`squal_embed.py`, `slat.py`) were throwaway and, per
S27's review of a different gate, **not reproducible from committed code**.
`hermes_runtime/knowledge/gates.py` fixes that class of gap for knowledge:

- `python -m hermes_runtime.knowledge.gates recall [questions.json]` — runs a
  labelled `[{q, gold:[page_id,...]}]` set through the real `retrieve()`,
  scores recall@3, prints PASS/FAIL against the 80% bar. Seeded with the
  spike's 30 synthetic questions, checked in at
  `hermes_runtime/knowledge/fixtures/synthetic_gate_questions.json`.
- `python -m hermes_runtime.knowledge.gates latency` — warms the query
  embedder (steady-state, not cold-load), times the **hybrid** retriever's
  in-turn p95 including embedding inference, gates at p95 < 800ms, and
  separately re-verifies `KnowledgeDriver`'s deadline still degrades a
  forced-slow path to the governed miss.

**This corrects audit finding 1.** The spike's `slat.py` measured
`statement_timeout`-guarded raw FTS SQL only — the rejected rung — and the
escalation rule "re-run S-LAT for the selected rung" was never executed. The
S12 latency gate measures the **shipped hybrid retriever** (embedding
inference included), the rung actually in production.

**Measured, live corpus (167 chunks, real embedder, 2026-07-20):**

| Gate | Result |
| --- | --- |
| recall@3 (30 synthetic questions) | **22/30 = 73%** — FAIL vs. the 80% bar. Matches the spike's embedding-rung number; the interim dev-time gate, not the final one (see below). |
| hybrid in-turn p95, embedding included | **p95 = 48.4ms** (p50 31.9ms, p99 51.8ms, max 64.6ms) — PASS vs. the 800ms bar, ~750ms of headroom. |
| deadline degrade, forced-slow hybrid path | governed miss in 815ms (bounded by the 800ms deadline, not the forced 2s sleep) — PASS. |

**Corpus-size projection (FR-7b's "projected corpus size" clause).** Measured
at the real 167-chunk corpus rather than a synthetically padded ~1500-chunk
one (the brief's documented alternative to padding): the two steps that scale
with corpus size — the `SELECT * FROM knowledge_chunk` fetch and the
in-process cosine matrix build/matmul — are a small, roughly linear fraction
of the current 48ms p95, which is dominated by the (corpus-size-independent)
ONNX embedding inference call. A 9× corpus increase to ~1500 chunks would add,
at most, a low-double-digit-millisecond delta to those two steps — nowhere
near consuming the ~750ms of headroom to the 800ms bar. This is a documented
projection, not an empirical padded-corpus measurement; padding the shared
`toee_knowledge` DB in place during a multi-agent session risked contaminating
other in-flight work on the same branch, so it was not done here. If future
corpus growth approaches the projection's assumptions, re-run
`gates.py latency` against the grown real corpus directly.

**The 73% recall number is the interim, synthetic-set gate, not the final
one.** FR-7's real gate is recall@3 ≥ 80% on the ~30 owner-supplied real
questions (PAC-10) — that question set, the tune-and-re-run loop if it
misses, and sign-off are **S32**'s scope, not this slice's. This ADR and the
gates harness exist so S32 has a repeatable, checked-in tool to run against
the real set, not so this slice claims the final bar is met.

## What this supersedes

**Superseded (implementation mechanisms):** ADR-0001's weekly **Knowledge
Crawl** Hermes Skill and storage through Hermes Native Memory; ADR-0031's
**Shopify Knowledge Sync** + **Tavily Gap Crawl** dual-track weekly rebuild
and its Hermes-Native-Memory write target. None of these were ever built;
Path Y-embed hybrid, in a separate `toee_knowledge` database, replaces them.

**Still holds, from both ADRs:**
- The two-layer split — Public Site Knowledge vs. governed Operational Policy
  Knowledge — is unchanged.
- **Live conversation facts (price, inventory, order status) come from live
  Shopify/QBO tool reads, never from RAG** — ADR-0001's and ADR-0031's central
  rule, untouched by the mechanism swap.
- Public FAQ/policy copy is maintained on the website, not a second
  hand-authored corpus — Shopify remains the corpus source (S07's ingestion
  job reads the Shopify connector), vindicating ADR-0031's source choice even
  as its sync *mechanism* (weekly Skill, Tavily gap crawl) is replaced.
- ADR-0002 and ADR-0030's now-dead crawl/web-backend mechanisms referenced
  from the L5 map (`docs/architecture/memory-layers.md`) are noted there as
  practically superseded in the same way; this ADR is the formal record for
  ADR-0001/0031 specifically, since those are the two FR-2/NFR-8 name.

## Open question carried from FR-2 (not decided here)

**Where does the authoring/review gate live for Knowledge content?** FR-2
scopes ingestion (Shopify connector → chunk → embed → index) and its
boundary-check lint (live-fact / governed-policy content flagged into a
human-review report, not silently indexed) — but not who *authors* Knowledge
content or where a change gets *reviewed* before it reaches the corpus. Two
shapes are on the table, not mutually exclusive:

- **Shopify-sync governance**: content is edited directly in Shopify (pages,
  blog articles, policies) by whoever already has Shopify admin access; the
  ingestion job's own boundary-check lint is the only automated gate; there is
  no PR-style review step before content is live on the site (and thus
  eligible for the next ingest).
- **`brain/` git-PR governance**: net-new or sensitive Knowledge content goes
  through a git-tracked directory with normal PR review before it's indexed,
  independent of whether it's also published to Shopify.

A hybrid (Shopify for existing/simple pages, `brain/` for net-new or
higher-stakes authored knowledge) is plausible but not chosen. This is
explicitly **not decided by this ADR** — it is recorded here, per NFR-8, so it
is not silently resolved by whichever path an implementer happens to take
next. Owner: the L5 track's next authoring-flow slice.

## Consequences

- L5 Knowledge is now `decided AND built` rather than `decided, not built` —
  `docs/architecture/memory-layers.md`'s L5 row is updated in this same PR to
  cite this ADR.
- The gates harness (`gates.py`) is a permanent, checked-in artifact — future
  corpus/content/model changes get a repeatable regression check instead of a
  one-off spike number that rots.
- The FR-2 authoring/review-gate question stays open; anyone building the
  ongoing refresh/authoring flow must resolve it explicitly (a follow-up ADR),
  not assume either shape by default.
- Short-doc under-retrieval (e.g. thin Contact/brand pages, noted in
  `CONTENT-GAPS.md`) and embedding-model choice remain open tuning
  questions for S32, not blocked by this ADR.

## Considered options

- **gbrain / Path X (rejected)** — see Decision §1.
- **pgvector instead of in-process cosine (rejected for now)** — at 167
  (and even a projected ~1500) chunks, holding all embeddings in memory and
  computing cosine similarity in numpy is simpler to operate (no extension,
  no index tuning) and already fast (Decision §4's measured p95). Revisit if
  the corpus grows enough that in-process cosine's O(n) scan becomes the
  bottleneck.
- **Keep ADR-0001/0031's weekly-Skill mechanism (rejected)** — never built,
  and the spike showed an in-house synchronous retriever is both simpler to
  reason about (no rebuild-window staleness) and fast enough to run at
  request time instead of a pre-built weekly index.
- **Pad the shared corpus to ~1500 rows for an empirical latency number
  (rejected for this slice)** — see Decision §4's projection note; the risk of
  contaminating a shared multi-agent branch's live corpus outweighed the
  value of an empirical number over a well-grounded linear-scaling projection
  with ~750ms of headroom to spare.

## Verification

- Live, real corpus (167 chunks), real embedder, real Postgres — see Decision
  §4's measured table; full CLI output recorded in `.superpowers/sdd/0.0.3-S12-report.md`.
- Unit: `hermes-runtime/tests/test_knowledge_gates.py` — recall computation
  (hit/miss/recall@3 arithmetic, bar comparison, empty-set edge case),
  latency-report percentile math and PASS/FAIL threshold, latency-harness
  call-count structure (fake retriever), and the deadline-degrade check
  against the real `KnowledgeDriver` with a forced-slow fake retriever —
  all injected, no live DB or embedder required for CI.
- Pre-existing, unaffected by this ADR: `test_knowledge_retriever.py` (RRF
  fusion, cosine ranking), `test_knowledge_driver.py` (deadline/governed-miss
  behavior), `test_knowledge_config.py`, `test_knowledge_migrate.py`,
  `test_knowledge_ingest.py` — all green.
