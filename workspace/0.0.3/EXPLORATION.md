# 0.0.3 — Exploration (NOT a PRD)

- **Status:** exploration only. A holding space for what **0.0.2 deferred** (moved
  here in full at 0.0.2 kickoff), plus a **live scratchpad** for ideas that surface
  while building 0.0.2. Nothing here is committed scope; each candidate graduates
  to a PRD only after a brainstorm.
- **Builds on:** 0.0.2 (govern + harden — [EXPLORATION](../0.0.2/EXPLORATION.md),
  branch `feat/0.0.2-memory-governance`). 0.0.1 shipped Customer Memory (PR #54).
- **Date opened:** 2026-07-14 (at 0.0.2 kickoff)

---

## How to read this

Same convention as 0.0.2's exploration: each candidate is sized (XS/S/M/L) and
carries **options with trade-offs**, not a decision. The **likely 0.0.3 headline
is the knowledge layer** — the one big capability 0.0.2 deliberately deferred so it
gets a full spike → PRD cycle instead of being rushed. When a candidate is chosen,
it graduates into `workspace/0.0.3/PRD.md`.

**Candidate index**
1. Knowledge layer (gbrain vs in-house retriever) — *capability* (L) — **likely headline**
2. Write-guardrail "propose → confirm" (option D) — *governance* (L)
3. Customer Memory retention sweep — *compliance* (M, conditional)
4. Connection pooling — *scale* (M, conditional)
5. Cross-channel memory continuity (email / voice) — *capability* (M, conditional)
6. Customer memory transparency & control — *privacy/compliance* (M)
7. Memory effectiveness instrumentation — *measurement* (S–M)

---

## Candidate 1 — Knowledge layer (the deferred headline) — L

### Why
The knowledge the agent uses for company/brand/product is hollow: persona + 6
policy slots; `toee_knowledge_search.search_public_site` is a 2-entry mock; the
ADR-0001/0002/0031 weekly RAG/crawl was never built. A real, retrievable knowledge
layer lets the agent answer "what's your return policy / does this tire fit / who
are you" from authored content instead of nothing. Explored in the 0.0.1
[design spec](../../docs/superpowers/specs/2026-07-10-memory-architecture-activation-design.md)
(§M2) and [PRD §4.2](../0.0.1/PRD.md) (FR-8…FR-10, PAC-8).

### The boundary (unchanged from 0.0.1, restated because it governs everything here)
Knowledge is a **shared, non-PII, retrievable corpus** — strictly separate from:
- **live facts** (price/stock/order/AR) → always real-time Shopify/QBO tool reads;
- **operational policy slots** → the 6 eval-gated slots (KnowledgeOps), untouched;
- **brand voice / behavior** → the `persona.py` system prompt;
- **customer PII / preferences** → the Customer Memory datastore.

`brain/` (the knowledge content) **never** holds any of those.

### Two build paths (this is the real decision)

**Path X — gbrain as the backend.** github.com/garrytan/gbrain: git markdown →
Postgres+pgvector, hybrid retrieval (vector + BM25 + knowledge graph), MCP/HTTP.
- Pros: sophisticated retrieval out of the box; its own dedup/citation/contradiction
  loop; philosophically aligned (git markdown + Postgres system-of-record).
- Cons: large external dependency (700+ open issues, v0.x, fast-moving); an extra
  service to deploy + upgrade; must be locked to read-only behind our governed tool.

**Path Y — in-house retriever over `brain/` markdown.** Chunk `brain/` markdown →
index (start with BM25/keyword or a small embedding model into a `knowledge_chunk`
table in a **separate** Postgres DB) → `toee_knowledge_search.search_public_site`
returns top-k chunks.
- Pros: fully owned, no third-party service, trivial to reason about + secure;
  reuses the existing datastore patterns; good enough for a curated FAQ-sized corpus.
- Cons: no knowledge-graph retrieval; we build/maintain the chunker+index; quality
  ceiling lower than gbrain on a large corpus.

**Lean:** start with **Path Y (in-house, BM25 first)** for a v1 — the corpus is
curated and small (company/brand/product/FAQ), retrieval quality needs are modest,
and it avoids betting a customer-facing path on a churny dependency. Revisit gbrain
(Path X) if the corpus grows and retrieval quality demands graph-aware search.
*This reverses the 0.0.1 lean toward gbrain — worth an explicit call after the spikes.*

### Spikes (hard gates, measure before committing to either path)
1. **Latency** — top-k retrieval must return **< 800 ms** for an in-turn SMS tool
   call (measured on the real corpus size). Synthesis/LLM-in-the-loop retrieval is
   **out of scope in-turn** regardless of path. *Pass/fail: p95 < 800 ms.*
2. **Retrieval quality** — on a hand-labeled set of ~30 real customer questions,
   the right chunk in top-3. *Pass/fail: precision@3 acceptable to the product owner.*
   (This is where Path X might beat Path Y — spike both if quality is borderline.)
3. **Deployment isolation** — the knowledge index lives in a **separate database**
   from the business datastore (knowledge carries no PII; physical separation).
   *Pass/fail: index reachable, business DB untouched, connection isolated.*

### Design sketch — the driver seam (same for both paths)
- Tool surface unchanged: the agent still sees only the allowlisted
  `toee_knowledge_search`. `search_public_site` is backed by a
  `GbrainKnowledgeDriver` **or** `BrainRetrieverDriver` injected via the same
  `extra_drivers` seam S04/S20 use; `search_operational_policy` keeps reading the
  policy slots (untouched).
- **Degradation:** retriever timeout/unavailable → governed `found=false` (the
  existing knowledge-gap path); the turn never fails on knowledge retrieval.
- **In-turn = retrieved chunks, not synthesized answers** — so a synthesis error
  can never be relayed as fact (the agent grounds on cited chunks).
- **Security:** for Path X, gbrain's write/admin tools are never exposed to the
  customer agent (read-scoped credential only). For both, the retrieval **query**
  (the customer's message) is sanitized so PII doesn't leak into knowledge-store logs.

### `brain/` content taxonomy (what staff author)
Markdown under `brain/` (same-repo subdir, per 0.0.1 lean), page types e.g.:
`company-profile`, `brand-story`, `product-education` (tire specs/education,
non-live), `faq`, `policies-plain-language` (customer-friendly restatement — but
NOT the governed policy-slot copy), `tire-knowledge`. A **boundary lint** in the
PR flow rejects content that restates a policy slot verbatim or a live fact.

### Authoring / publish flow (git = the gate)
staff write markdown → PR review (the human gate; ADR-0041 exempts public-site
knowledge from the eval gate, so no conflict) → merge → index sync (Path X: gbrain's
own loop; Path Y: a re-index step) → retrievable. No live facts / policy copy / PII
ever committed.

### Terminology / ADR deliverables (ship with the layer)
- Redefine **Public Site Knowledge** = customer-facing content authored in `brain/`,
  indexed/retrieved by the chosen retriever.
- Mark **Shopify Knowledge Sync** / **Tavily Gap Crawl** glossary entries superseded
  by the chosen ingestion.
- New ADR recording the Path X vs Y decision and superseding ADR-0001/0031's
  *implementation* mechanisms (their live-facts rule stays).

### Sizing
- Path Y v1 (BM25 + `brain/` + driver + authoring + terminology/ADR): **M**.
- Path X (gbrain deploy + driver + isolation + the above): **L**.
- Spikes: half a day–2 days before committing.

### Open questions
- Path X vs Y (the core call) — resolve after the quality spike.
- Same-repo `brain/` vs a separate content repo (0.0.1 leaned same-repo).
- KnowledgeOps overlap: who authors/reviews `brain/` vs the policy slots?
- Does PAC-8 (grounded knowledge) need synthesis, or are cited chunks enough for SMS?

---

## Candidate 2 — Write-guardrail "propose → confirm" (option D) — L

*Deferred from 0.0.2, which shipped the lightweight A+B+E+NFR-3 guardrail. This is
the governance-faithful north star; promote if UAT of the 0.0.2 autonomous-write
path feels loose.*

The governance-faithful shape, and it **reuses everything 0.0.1 built**:
- The Copilot draft agent does **not** write directly. Instead it emits a
  **structured suggestion** ("suggest setting `contact_time_preference` =
  'after 5pm'") as part of its draft output.
- The Workbench **Customer Preferences panel** (S18) renders the suggestion as a
  *pending* proposal with Accept / Dismiss.
- **Accept** routes through the existing governed UI write path (S16/S17 dispatch
  route → `employee_confirmed`). So the actual persist is always a confirmed,
  attributed employee action — exactly ADR-0111.
- Net effect: this **supersedes gap #2's direct write** (the draft agent proposes;
  it never persists). If we adopt D, we would *disable* the S20 autonomous write
  (revert to read-only on the draft turn, i.e. option C) and add the proposal
  surface. Cleanest long-term model; largest build.

**Why it's the target:** D makes the whole "can the LLM write autonomously"
question moot by construction (it can only *propose*). The 0.0.2 A+B+E guardrail
is the honest, cheap interim; D is where the governance story wants to land.
**Size:** L.

---

## Candidate 3 — Customer Memory retention sweep (RK-9) — M (conditional)

**Why.** 0.0.1 deferred the retention job. Provisional slots accumulate (every
unmatched caller who states a preference makes a row that may never merge or
expire); verified slots have no sweep either. ADR-0004/0116 define the policy; the
columns (`created_at`, `last_interaction_at`) exist. **Shape:** a scheduled sweep
that ages/deletes `customer_memory_slot` rows past retention per the ADR-0004
classes. **Open:** per-slot-kind windows? provisional vs verified TTLs? where the
job runs (ties to the deferred Cloud Tasks/Cloud SQL slice). **Size:** M.
*Condition-gated on corpus volume.*

---

## Candidate 4 — Connection pooling (RK-7, conditional) — M

**Why.** 0.0.1 opens ~2–3 Postgres connections per turn (merge + read + write), no
pool (ADR-0142 deferred pooling to the cloud slice). Fine at SMS volume; a scaling
cliff later. **Only pursue if load testing shows it matters.** Ties into the
deferred Cloud SQL/Cloud Run slice. **Size:** M.

---

## Candidate 5 — Cross-channel memory continuity (email / voice) — M (conditional)

**Why.** Memory binds to `shopifyCustomerId` when verified, so a **verified**
customer's preferences already follow them across channels. But **provisional**
memory is per-channel (`provisional:sms:{E.164}`), and the VA is moving toward
email (ADR-0083/0123) and shares an SMS/voice identity (ADR-0013). The
cross-channel provisional story (and how email/voice turns read+inject memory) is
undefined.

**Possibilities:** extend read-injection to the email/voice turn paths (they're
separate seams like Copilot was); decide whether provisional memory should merge
across a customer's linked channel identities once the Identity Graph links them
(0.0.1 explicitly parked cross-channel provisional merge as an ADR-0112 non-goal —
revisit here). **Open:** which channels are actually shipping in this window?
**Size:** M (per channel).

---

## Candidate 6 — Customer memory transparency & control (privacy/compliance) — M

**Why.** 0.0.1 stores durable per-customer preferences. Today there's no path for a
customer to know what's stored or to have it removed, and no supervisor view/audit
of a customer's memory beyond the rep's correction panel. SMS **opt-out** is
handled (Identity Graph), but memory-specific transparency is not. As the memory
corpus grows this becomes a real privacy/compliance surface (data-subject
access/deletion expectations).

**Possibilities:**
- **Customer-facing:** a governed way for a verified customer to ask "what do you
  remember about me?" and to clear it (a read/clear over their own slots, gated by
  verification — reuse the existing binding + a customer-safe summary).
- **Supervisor/admin view:** a Workbench admin surface to view/audit/clear a
  customer's memory + its change history (pairs with the `source` distinction +
  the actor column shipped in 0.0.2 Candidate 1).
- **Deletion honoring:** wire memory into whatever data-deletion process exists so a
  "forget me" removes preference slots too.

**Open:** what regulatory posture applies (region)? Is customer self-service in
scope, or supervisor-mediated only for v1? **Size:** M.

---

## Candidate 7 — Memory effectiveness instrumentation (measurement) — S–M

**Why.** We activated memory but have no signal on whether it *helps*. Before
investing more (Candidates 2/6 and cross-channel), it's worth measuring: how often
is memory injected, how often does the agent act on it, does it correlate with
faster/better resolution or fewer repeat questions.

**Possibilities:** extend the S11 per-turn observability into aggregate metrics
(injection rate, slots-populated distribution, merge rate, correction rate);
a lightweight dashboard or a periodic report; optionally an eval/UAT rubric for
"did the reply honor the preference" (note: 0.0.2 adds an LLM-judge for this on the
eval path — this candidate is the *production* aggregate view). **Open:** what's the
success metric the business cares about (CSAT, handle time, repeat-contact rate)?
**Size:** S–M.

---

## Tech debt / carried forward

Populate as 0.0.2's reviews surface debt it does not fix. Seeds:
- Any item from 0.0.2 Candidate 5 (cleanups) that ends up **descoped** — move it
  here. (Currently in 0.0.2 scope: the `honor_injected_preference` LLM-judge fix,
  the `no-unprompted-recall` scenario, the `_load_case_memory` swallow warning, and
  the `PREFERENCE_SLOTS` TS export.)
- **CI provisions no Postgres** — the datastore/E2E acceptance gate is enforced
  locally only, not in CI (flagged in the 0.0.1 UAT sign-off). Belongs to the
  Cloud slice.
- **§6.4 audit-model wording divergence** — slot metadata + a dedicated merge-audit
  table + structured logs, vs the PRD's literal `workbench_audit_log` wording.
  Already on record (S13/S14).
- **Third `_require_slot` near-duplicate** — deferred from 0.0.1 review; low-risk
  hygiene.

## Live scratchpad — 0.0.2 dev spillover

Dump ideas here the moment they surface while building 0.0.2, so they are not lost;
triage at 0.0.3 kickoff. Format: `(date) one-line idea`.

- (2026-07-14) opened — nothing yet.

---

## Explicitly parked (not 0.0.3 unless promoted)

- Cross-channel provisional **merge** (ADR-0112 v1 non-goal) — but see Candidate 5.
- External memory providers (mem0 / honcho — rejected in 0.0.1).
- Any change to how **live facts** are served (stay real-time Shopify/QBO reads).
- Synthesis-mode knowledge retrieval **in-turn** (latency + grounding risk).
