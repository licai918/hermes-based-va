# 0.0.2 — Exploration (NOT a PRD)

- **Status:** exploration only. Nothing here is committed scope. This is a
  possibility space for the next iteration; each candidate lists options,
  design sketches, and open questions to resolve **before** any of it becomes a PRD.
- **Builds on:** 0.0.1 (Customer Memory activation — [PRD](../0.0.1/PRD.md),
  branch `feat/0.0.1-customer-memory` / PR #54).
- **Date opened:** 2026-07-14

---

## How to read this

Each candidate is sized (XS/S/M/L, rough) and carries **options with trade-offs**
and, where useful, a **design sketch** — not a decision. Candidate 1
(write-decision guardrail) and Candidate 2 (gbrain / knowledge layer) are the two
the product owner asked to develop fully; the rest are things 0.0.1 surfaced,
deferred, or that the roadmap implies. When a candidate is chosen, it graduates
into `workspace/0.0.2/PRD.md` via brainstorm → PRD → slices.

**Candidate index**
1. Write-decision guardrail for Copilot memory writes — *governance* (M)
2. gbrain / knowledge layer — *capability* (L)
3. Customer Memory retention sweep — *compliance* (M)
4. Harden the `channel_identity_id` carve-out — *security* (S)
5. Carried-forward cleanups — *hygiene* (S)
6. Connection pooling — *scale* (M, conditional)
7. Customer memory transparency & control — *privacy/compliance* (M)
8. Cross-channel memory continuity — *capability* (M)
9. Memory effectiveness instrumentation — *measurement* (S–M)

---

## ✅ Route decision (2026-07-14) — SELECTED

Product owner (licai) selected the **"Govern + harden the shipped memory"** theme,
right after the 0.0.1 PAC sign-off and PR #54 merge.

**0.0.2 committed scope:**
- **Candidate 1 — write-decision guardrail** at the **A + B + E + NFR-3** depth
  (not D): prompt guard on the Copilot draft persona; a distinct `copilot_agent`
  `source` value for AI-draft writes; a `no-inferred-write` copilot eval; and
  persist the acting `actor_account_id` (NFR-3). Option **D** (propose→confirm) is
  recorded as the future north star, **out of 0.0.2 scope**.
- **Candidate 4 — remove the `channel_identity_id` carve-out** (lean (a):
  context-only binding; it was a stopgap superseded by S16).
- **Candidate 5 — carried-forward cleanups**, including the eval
  `honor_injected_preference` freebie fix and a new `no-unprompted-recall`
  scenario — the latter **discharges the PAC-2 eval-coverage follow-up** recorded
  in the 0.0.1 UAT sign-off.

**Stretch (only if capacity):** Candidate 7 (transparency) / Candidate 9
(instrumentation).

**Deferred:** Candidate 2 (knowledge layer) → its own **0.0.3** with a full
spike→PRD cycle. Candidates 3 / 6 / 8 stay condition-gated (retention volume /
load / channel rollout).

**One ADR** covers the clustered governance surface: the new `source` value, the
carve-out removal, and the actor-attribution column.

**Next:** rebase this branch onto `main` (shipped 0.0.1) → point `workspace/CURRENT`
at 0.0.2 → brainstorm → `workspace/0.0.2/PRD.md` → slices for Candidates 1 / 4 / 5.

---

## Candidate 1 — Write-decision guardrail for Copilot memory writes (fully developed)

### Why
0.0.1 / S20 connected gap #2: the Copilot **AI drafting agent** can now
**autonomously persist** `toee_customer_memory.upsert_preference` writes (they
reach Postgres under the correct customer key). The guardrails today are
**integrity-only**:
- `source` framework-derived from the profile (model can't forge `customer_explicit`);
- binding key derived from `context.identity` (can't target another customer);
- fail-closed `policy_blocked` when no identity resolves;
- slot constrained to the fixed four-slot enum.

**The gap:** no authorization gate on *whether/when* the model writes, and no
prompt instruction constraining it. A draft-turn write is tagged
`employee_confirmed` even though no explicit confirmation happens at write time.
ADR-0111's intent is "writes happen after employee confirmation."

### Options

| # | Approach | Enforcement | Cost | Notes |
| --- | --- | --- | --- | --- |
| **A** | Prompt-level guard (draft persona: write only on explicit stated preference, never inference) | Soft (LLM behavior) | S | Cheapest; pair with eval (E). |
| **B** | Distinct `source` value for AI-draft writes (`copilot_agent`) | Honest audit, not prevention | S | Enum + handler; column already `text`, no migration. |
| **C** | Read-only memory on the draft turn (writes only via the UI button) | Hard (allowlist) | M | Cleanest, but reverses the gap-#2 decision. |
| **D** | Propose → confirm loop (agent proposes; rep confirms; then it persists) | Hard (human in loop) | L | Most faithful to ADR-0111; reuses S16–S18. |
| **E** | Copilot "no-inferred-write" eval (mirror external scenario 26) | Regression guard for A | S | Locks A; not a guard alone. |

### Design sketch — the lightweight combo (A + B + E)

- **A — prompt guard.** Add to the Copilot draft persona (`copilot_turn._SYSTEM_MESSAGES`)
  a rule mirroring the external persona's existing discipline: *"Only record a
  customer preference (`toee_customer_memory.upsert_preference`) when the customer
  has explicitly stated a durable preference that appears in this case's
  conversation. Never infer a preference from tone, history, or a single order.
  When unsure, do not write."* Soft, but it's the same mechanism that already
  keeps the external agent honest (eval scenario 26 green).
- **B — honest audit label.** Add a `source` value so an AI-draft write is
  distinguishable from a rep's deliberate UI correction: the write path derives
  `source` from *profile + whether the call is a draft-turn tool call vs a
  dispatch-route (UI) call*. Concretely: dispatch-route (UI button) →
  `employee_confirmed`; copilot draft-turn tool call → a new `copilot_agent`
  value. Enum lives in `mock/memory.py` (`MEMORY_SOURCE_VALUES`), validated in the
  handler; the `customer_memory_slot.source` column is already `text` (no
  migration). This makes the audit trail (§6.4) *truthful* and lets a supervisor
  review AI-written preferences (ties to Candidate 7/9).
- **E — eval.** A `30-copilot-memory-no-inferred-write` scenario asserting the
  draft agent does not persist a preference from inference. Mirrors external
  scenario 26 on the copilot path.

### Design sketch — the "correct" version (D: propose → confirm)

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

### Audit / acceptance
- Audit: every persisted write carries `source` distinguishing UI-confirmed vs
  agent-inferred (option B) — feeds the §6.4 trail and any supervisor review.
- Acceptance: eval E green on the copilot path; for D, a UAT that a suggestion
  never persists without an explicit Accept, and Accept produces an
  `employee_confirmed` row.

### Recommendation (for discussion, not decided)
Ship **A + B + E** now (cheap, honest, low-risk), and treat **D** as the target
architecture — because D makes the whole "can the LLM write autonomously" question
moot by construction (it can only *propose*). If UAT of the autonomous path feels
loose, jump straight to D. Avoid C-in-isolation (it just turns the feature off
without the proposal UX).

### Also fold in here — NFR-3 actor attribution gap (from PR #54 review)
The employee-correction write **resolves the acting rep** (`actor_account_id` →
`context.user_id` in `tool_dispatch_app`) but then **drops it** — `_upsert_preference`
persists no actor column, so `source=employee_confirmed` never records *which* rep
made the change. PRD NFR-3 says "every memory write is attributable." Defensible
under the amended §6.4 (the write is attributable *in kind*), but the actor is
resolved-then-dropped. **This pairs naturally with option B**: when we add the
`source` distinction, also persist the acting `actor_account_id` (and, for a merge,
already covered by the merge-audit row). Cheap column add; makes "which rep
corrected this" auditable (feeds Candidate 7's supervisor view). **Size:** XS.

### Open questions
- Does the draft agent *need* to write at all, or is "propose to the rep" (D)
  always better? (If yes → D, and S20's direct write becomes a stepping stone.)
- Is a new `source` value enough, or does an AI-inferred write need supervisor
  review before it counts as active (ties to Candidate 7)?
- Persist the acting rep (NFR-3 above) alongside the `source` value?
- Resolve together with Candidate 4 (the `channel_identity_id` carve-out).

**Size:** A+B+E = S–M; D = L.

---

## Candidate 2 — gbrain / knowledge layer (fully developed)

### Why
The knowledge the agent uses for company/brand/product is hollow: persona + 6
policy slots; `toee_knowledge_search.search_public_site` is a 2-entry mock; the
ADR-0001/0002/0031 weekly RAG/crawl was never built. A real, retrievable
knowledge layer lets the agent answer "what's your return policy / does this tire
fit / who are you" from authored content instead of nothing. Explored in the 0.0.1
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

## Candidate 3 — Customer Memory retention sweep (RK-9)

**Why.** 0.0.1 deferred the retention job. Provisional slots accumulate (every
unmatched caller who states a preference makes a row that may never merge or
expire); verified slots have no sweep either. ADR-0004/0116 define the policy; the
columns (`created_at`, `last_interaction_at`) exist. **Shape:** a scheduled sweep
that ages/deletes `customer_memory_slot` rows past retention per the ADR-0004
classes. **Open:** per-slot-kind windows? provisional vs verified TTLs? where the
job runs (ties to the deferred Cloud Tasks/Cloud SQL slice). **Size:** M.

---

## Candidate 4 — Harden the `channel_identity_id` carve-out (now has teeth)

**Why.** S02 left an `internal_copilot`-only fallback: when `context.identity`
yields nothing, `resolve_customer_memory_binding` honors a **model/param-supplied**
`channel_identity_id` → `provisional:{channel_identity_id}`. Pre-0.0.1 this only
hit mock; **post-S20 a model that emits that param during a draft can direct a
persisted write to a provisional key it names.** The draft path binds from context
first, so it's not the common case, but the carve-out is live. **Options:**
(a) remove it entirely (context-only binding; the UI dispatch route passes
`case_id`, not this param) — **lean (a)**, it was a stopgap superseded by S16;
(b) restrict it to a non-model actor; (c) leave it + an eval it's never used.
**Size:** S. Resolve with Candidate 1.

---

## Candidate 5 — Carried-forward cleanups from 0.0.1

Low-risk hygiene the reviews flagged and parked (each XS–S):
- **De-dup `_customer_memory_extra_drivers`** — verbatim in `openrouter.py` and
  `copilot_turn.py`; hoist to `tool_backend.py` (already exports `memory_enabled`
  + `select_tool_driver`); kills drift on a security-adjacent gate.
- **Copilot `_load_case_memory` identity-lookup swallow** — the `load_case_identity`
  branch still swallows silently (S11 logged only the other branch); add the
  PII-safe warning.
- **Rename the S15 characterization test** — `test_dispatch_route_correction_persists_but_misses_...`
  now documents the *legacy* carve-out, not an open bug; the name misleads (ties to Candidate 4).
- **Workbench preferences panel visual polish** — S18's panel is an un-renormalized
  `flex` insert; wants a real-browser layout pass (also on the UAT list).
- **Export the slot constant on the TS side** — `PREFERENCE_SLOTS` is a hand-written
  literal in `apps/workbench` because `MEMORY_PREFERENCE_SLOTS` isn't exported from
  `@toee/domain-adapters`; export + import so a 5th slot can't silently drift.
- **Fix the eval `honor_injected_preference` freebie (from PR #54 review)** —
  `turn_result.py:73` sets `honored_injected_preference=True` whenever any
  `memory_preset` exists, and `assertions.py:198` then always passes. So scenarios
  25/27/28 that list `honor_injected_preference: true` prove nothing — only their
  `must_not_contain` legs discriminate. Make the assertion actually inspect whether
  the injected preference was honored in the reply, so the R3/R5b/PAC-1 eval legs
  are genuine (today the datastore/E2E suites carry that proof, not the eval). Also
  wire/verify `MEMORY_SOURCE_VALUES` isn't the only drift guard. **Size:** S.
  *(Related: PAC-2 "no over-recall" has NO eval leg at all — §6.5 says "eval + UAT";
  today it's UAT-only. Add a `no-unprompted-recall` scenario when hardening these.)*

---

## Candidate 6 — Connection pooling (RK-7, conditional)

**Why.** 0.0.1 opens ~2–3 Postgres connections per turn (merge + read + write), no
pool (ADR-0142 deferred pooling to the cloud slice). Fine at SMS volume; a scaling
cliff later. **Only pursue if load testing shows it matters.** Ties into the
deferred Cloud SQL/Cloud Run slice. **Size:** M.

---

## Candidate 7 — Customer memory transparency & control (privacy/compliance)

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
  customer's memory + its change history (pairs with the `source` distinction from
  Candidate 1B).
- **Deletion honoring:** wire memory into whatever data-deletion process exists so a
  "forget me" removes preference slots too.

**Open:** what regulatory posture applies (region)? Is customer self-service in
scope, or supervisor-mediated only for v1? **Size:** M.

---

## Candidate 8 — Cross-channel memory continuity (email / voice)

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

## Candidate 9 — Memory effectiveness instrumentation (measurement)

**Why.** We activated memory but have no signal on whether it *helps*. Before
investing more (Candidates 1/7/8), it's worth measuring: how often is memory
injected, how often does the agent act on it, does it correlate with
faster/better resolution or fewer repeat questions.

**Possibilities:** extend the S11 per-turn observability into aggregate metrics
(injection rate, slots-populated distribution, merge rate, correction rate);
a lightweight dashboard or a periodic report; optionally an eval/UAT rubric for
"did the reply honor the preference." **Open:** what's the success metric the
business cares about (CSAT, handle time, repeat-contact rate)? **Size:** S–M.

---

## Cross-cutting

- **Pick a 0.0.2 theme.** These split into two coherent themes — choosing one
  keeps the iteration focused:
  - **"Govern + harden the memory we just shipped"** = Candidates 1, 4, 5, 7, 9
    (mostly S–M; directly hardens 0.0.1; low external risk). A natural, tight
    follow-on to 0.0.1.
  - **"Add the knowledge layer"** = Candidate 2 (L; the big new capability;
    external-dependency risk gated by spikes).
  - My lean: **0.0.2 = govern + harden (1/4/5), with 7 and 9 as stretch**; make
    the **knowledge layer its own 0.0.3** so it gets a full spike→PRD cycle rather
    than being rushed. But if the business need is "the agent must answer product
    questions," flip that and make Candidate 2 the 0.0.2 theme.
- **Sequencing vs 0.0.1 merge.** Candidates 1/4/5 touch the exact memory code
  0.0.1 just wrote — do them **right after PR #54 merges** to avoid churn/conflicts.
- **Governance items cluster.** Candidates 1, 4, 7 all touch the write/binding
  governance surface; if 0.0.2 is the "govern" theme, design them together (one
  ADR update covering source values, the carve-out removal, and the transparency
  posture).

## Explicitly parked (not 0.0.2 unless promoted)
- Cross-channel provisional **merge** (ADR-0112 v1 non-goal) — but see Candidate 8.
- External memory providers (mem0/honcho — rejected in 0.0.1).
- Any change to how live facts are served (stay real-time Shopify/QBO reads).
- Synthesis-mode knowledge retrieval in-turn (latency + grounding risk).
