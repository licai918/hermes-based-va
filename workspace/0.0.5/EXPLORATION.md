# 0.0.5 — Exploration

> Status: **exploration**. Candidates here are directions with evidence, not commitments.
> The 0.0.3 pipeline applies before any build: grill → PRD (gap-audited) → issue slices.
> 0.0.4 (job queue + scoring) is in flight and deliberately NOT expanded by this document.

---

## Candidate 1 — L7 Semantic Lexicon: a self-growing, admin-governed semantic layer

### The problem (owner-stated, 2026-07-21)

The agent needs **domain language**, and that language changes as the business grows:

- Company aliases: `TOEE` ≡ `TOEE TIRE`.
- Notation normalization: a customer writes `2055516` / `205 55 16` / `20555r16` and means
  `205/55R16`.
- Contextual defaults: a size given without a season defaults to the CURRENT season's tire
  (summer now, winter in winter) — **and the agent must confirm before acting on the default**.
- Tires are only the example: new product lines (wheels, accessories, …) and business changes
  will keep introducing new vocabulary. The layer must grow **without a developer deploy** for
  routine entries, and it must grow **from conversations**: when the agent asks
  “do you mean 205/55R16 summer tires?” and the customer says yes, that confirmed mapping should
  become a **candidate** entry an admin can approve / edit / reject / retire — plus manual add.
  A self-reinforcing loop, human-gated.

### Current state (verified in code, 2026-07-21)

| Carrier | Fact |
| --- | --- |
| LLM default understanding | `persona.py` names the company and nothing else — **no** size/alias/season conventions anywhere. `2055516 → 205/55R16` currently rides entirely on the model’s own guess: unverifiable, untested, unauditable. |
| Prompt conventions | `_TOOL_PARAM_CONVENTIONS` (copilot_turn.py) exists as a mechanism (QBO link-check, bare order numbers) but contains zero tire-domain vocabulary. |
| Deterministic normalizers | `normalize.py` has `normalize_e164` / `canonicalize_email` — the exact pattern precedent, but no tire-size parser. |
| L5 knowledge | ~3 chunks mention size-like text; dense embeddings are weak on digit strings (2055516 vs 2056515 are near-identical vectors). |
| L6 agent experience | The propose→confirm→inject loop exists (0.0.3 S22-S25) but holds free-text notes, not structured mappings, and applies them as soft guidance only. |
| Seasonal defaults | Nowhere. |

### Options considered

| Option | Verdict | Why |
| --- | --- | --- |
| A. Prompt-only glossary (admin edits → injected) | ◑ partial | Fully dynamic, but soft guarantees, unbounded context growth, unreliable on digit strings. Keep only as ONE application seam, never the store. |
| B. Code-table lexicon + PR “graduation” | ✗ alone | Deterministic, but every routine entry needs a developer deploy — fails the self-serve requirement. Survives only as the home for regex normalizers (below). |
| **C. DB-backed governed lexicon + dual-seam application + fork capture** | ✅ **recommended** | Admin self-serve CRUD; confirmed entries apply **deterministically** (table-driven exact match is still deterministic); capture rides the already-proven governed pipeline. |
| D. Embedding/RAG synonym learning | ◑ fallback only | No hard guarantees for codes. |
| E. Periodic fine-tuning | ✗ | Breaks NFR-6 eval determinism; cost; model churn. |

**Philosophy: “port the loop, not the store” (ADR-0140), applied once more** — reuse the L6
*pattern* (status lifecycle, propose tool, injection scan, admin decide queue, confirmed-only
apply, eval pin), build the lexicon its *own* structured table.

### Recommended architecture (Option C, mapped to existing code)

**Store — `semantic_lexicon` (new migration):**
`id · domain (tire|company|wheel|…) · entry_kind · surface_form · canonical_form ·
status (proposed|confirmed|rejected|retired) · provenance (admin_manual|conversation_confirmed) ·
evidence (case_id / exchange excerpt) · proposer_context · decider_account_id · decided_at ·
hit_count · created_at · updated_at`, with `UNIQUE(domain, surface_form)`.

**`entry_kind` — three kinds, graded by determinism (the design crux):**
- `alias` — exact surface→canonical (`TOEE→TOEE TIRE`, `2055516→205/55R16`). Admin-editable
  freely; table-driven exact match stays deterministic.
- `normalizer` — pattern-class rules (tire-size regex). **The regex itself lives in code**
  (admin-editable regex is an incident factory); the table only stores which built-in normalizer
  a domain enables + parameters. New product line ⇒ dev adds one normalizer function, admin
  toggles it.
- `default_rule` — contextual defaults as structured fields
  (`condition: season=summer → default: summer tire → confirm: required`), never free text.

**Application — two seams, each eval-pinned (S25/S26 discipline):**
1. **Deterministic seam**: tool-dispatch param normalization (`search_products` / `get_product`
   consult confirmed aliases + enabled normalizers before the query). Process-level cache +
   version-bump invalidation (the S10 embedder-singleton pattern). Normalized-first also feeds
   L5 retrieval — normalization RAISES knowledge hit rate (synergy, not overlap).
2. **Prompt seam**: bounded top-N confirmed entries rendered as a fenced `<confirmed_lexicon>`
   block (exactly the `<confirmed_operational_learnings>` shape: confirmed-only, bounded,
   fail-closed skip, default-OFF on the eval record/replay path).

**Capture — the one NEW security decision (owner gate):**
“Customer said yes” must never be written by the external agent itself — 0.0.3’s hard boundary
(ADR-0152: external is read-only, never proposes) stands. Two options:
- **Recommended:** a **gateway-side post-turn review fork** proposes (the S23 pattern): the fork
  is internal infrastructure running AFTER the turn under the INTERNAL profile, with exactly one
  tool (`propose_lexicon_entry`), S22-style injection/PII scan on write, human gate after. The
  customer-facing agent still cannot write a single row; the proposer is the background fork.
  Requires a superseding note on ADR-0152 spelling out this fork-vs-agent distinction.
- Conservative fallback: capture on the copilot side only (rep-confirmed conversations) — zero
  new surface, weaker coverage; widen later.
Structured params (`surface_form, canonical_form, domain, evidence_turn`) extracted from the
governed tool RESULT (S14 discipline) — model prose never counts.

**Governance + metrics:**
Admin console = sibling of `AgentExperienceConsole`: list + Approve/Edit/Reject/Retire + manual
add (provenance=admin_manual). All write actions in `_AGENT_EXCLUDED_ACTIONS`, `insert_audit`
rows, framework-derived decider — the S24 `_decide_experience` handler shape is copy-paste.
Hit counting via `metric_event` (S26); a metrics tile surfaces zero-hit entries so admins retire
dead vocabulary — **the loop closes**.

### The full memory architecture after L7 (scope map + anti-gap/anti-overlap)

**L1-L7 at a glance** (the discriminating question per layer):

| Layer | Question it answers | Scope | Shape | Application |
| --- | --- | --- | --- | --- |
| L1 Identity | “who is this channel identity?” | per-customer | exact key | hard binding |
| L2 Conversation | “what was said?” | per-customer | verbatim | keyed read |
| L3 Operational | “what did the system/staff do?” | per-event | structured records | keyed/audit query |
| L4 Customer Memory | “what does THIS customer prefer?” | per-customer (PII) | 4 governed slots | exact injection |
| L5 Knowledge | “what are the company/product FACTS (prose)?” | shared, non-PII | corpus chunks | fuzzy top-k (soft) |
| L6 Agent experience | “what have we learned about HOW to do the job?” | shared, non-PII | free-text guidance | confirmed-only prompt guidance (soft) |
| **L7 Semantic lexicon** | “what does this WORD/NOTATION mean?” | shared, non-PII | structured mappings/rules | **deterministic normalization (hard)** + bounded glossary (soft) |
| (outside) | live business facts (price/stock/orders/AR) | — | — | tool reads, NEVER memory (standing rule) |

**Routing decision tree** (every branch terminates — no dead ends = no gaps):

```
Is it about ONE customer?
├─ yes → identity link? L1 | the words themselves? L2 | a case/action? L3 | a preference/habit? L4
├─ no — is it a LIVE business fact (price/stock/order)? → tool read; forbidden in every layer
└─ no — shared & static →
   ├─ expressible as surface→canonical or a structured rule (“X means Y”)? → L7
   ├─ prose fact a customer would ask, answer belongs on the website? → L5 (edit Shopify)
   └─ only expressible as a how-to paragraph? → L6  ← the catch-all shape
```

**The three easiest-to-blur boundaries, pinned:**
- **L6 vs L7**: if it CAN be structured it MUST be L7; only what can’t stays L6. Enforced
  mechanically, not by intent: ① the review fork’s prompt routes lexicon-shaped findings to
  `propose_lexicon_entry`, the rest to `propose_experience`; ② the admin queue gets a
  **re-classify** action (move a mis-filed entry to the other queue, not reject-and-retype);
  ③ a periodic **graduation sweep**: confirmed L6 notes that turn out to be structurable move to
  the L7 table (only regex normalizers graduate into code).
- **L5 vs L7**: L5 owns CONTENT (“what to know about 205/55R16”, prose, retrievable, may miss);
  L7 owns LANGUAGE (“2055516 IS 205/55R16”, mapping, must not miss). They compose: normalize
  first (L7), retrieve second (L5).
- **L4 vs L7**: SCOPE decides, not shape. “Customers write sizes as 2055516” → shared language →
  L7. “THIS customer’s ‘the usual spot’ means his side gate” → single-customer semantics →
  L4 (`delivery_habit_note`).

**Six structural anti-gap/anti-overlap mechanisms** (mostly already built):
1. **One governed write path per layer** (upsert_preference / propose_experience /
   propose_lexicon + admin CRUD) — the write TOOL determines the layer; one fact physically
   cannot enter two layers.
2. **Per-layer unique keys/tables** (L4 `UNIQUE(binding_key,slot)`, L7 `UNIQUE(domain,surface)`,
   L5 separate DB) — no storage-level overlap is possible.
3. **Per-layer injection fences** (`<untrusted_customer_memory>` / `<confirmed_operational_learnings>` /
   `<confirmed_lexicon>`) — scopes stay explicit on the model side too.
4. **Single audit source** (`workbench_audit_log`, framework-derived attribution) — every write
   to every layer is traceable and correctable.
5. **Boundary matrix** in `memory-layers.md` (“this never holds that”) — gains three L7 rows
   when the ADR lands: L7 never holds customer PII; never holds live facts; single-customer
   semantics always go to L4.
6. **Operational loop**: fork routing rules + admin re-classify + L6→L7 graduation sweep +
   L7 hit metrics (zero-hit retirement) — mis-filing isn’t “prevented by hope”, it is caught by
   routine process.

### Acceptance sketch (for the eventual PRD)

- `2055516`, `205 55 16`, `20555r16` typed in the simulator all retrieve the same product
  (deterministic seam proven end-to-end).
- In winter (or with the season rule toggled), a bare size defaults to winter tires and the
  agent **asks for confirmation** before quoting (judge-sampleable behavior).
- A simulated confirmation exchange (“do you mean 205/55R16?” → “yes”) produces a `proposed`
  lexicon entry visible in the admin queue; Approve makes it live (cache-bumped) without a
  deploy; Reject leaves no effect; both audited with decider.
- Admin manually adds / edits / retires an entry; hit counts visible on the metrics panel.
- Eval replay gate stays green with both seams pinned OFF (NFR-6).

### Draft slices (post-grill; sized like 0.0.3 slices)

1. **S-A `semantic_lexicon` store + governed tool + admin console** — migration, mock+PG twins,
   `propose_lexicon_entry` (scanned) + admin decide/CRUD actions (`_AGENT_EXCLUDED_ACTIONS`),
   console sibling of AgentExperienceConsole. (M)
2. **S-B capture** — review-fork extension (or copilot-only fallback) + the external-boundary
   decision + ADR-0152 superseding note. (M, owner decision inside)
3. **S-C application** — deterministic param-normalization seam + `<confirmed_lexicon>` prompt
   seam + eval pin + hit metrics + first seeded domain (tire sizes + company aliases + season
   rule). (M)

### ADRs this candidate will produce (written WHEN slices land, per repo convention)

1. **L7 decision ADR** — store-not-prompt, three entry kinds, dual-seam application, graduation
   mechanism, L6/L5/L4 boundary rows for the matrix.
2. **Capture-boundary note** — superseding note on ADR-0152 (fork-proposes vs agent-proposes),
   or folded into the L7 ADR.

### Open questions (grill fodder)

- Season source: date-derived (Toronto hemisphere) vs admin-set toggle? (lean: date-derived
  default + admin override row as a `default_rule`.)
- Normalizer validation: should a parsed size be verified against the live Shopify catalog
  (`search_products`) before the agent asserts it? (lean: yes — grounding beats parsing.)
- Bounded glossary N and selection (newest? per-domain quota? hit-ranked?).
- Does `default_rule` confirmation policy live in L7 rows or stay a persona-level discipline
  referencing L7 defaults? (lean: rule in L7, phrasing in persona.)

---

## Candidate 2 — Memory latency: make L1-L7 imperceptible (measured SLO, not hope)

### Current facts (verified)

- **Fast-ack already removes memory from the webhook path** (ADR-0103): the user-felt wait is
  the async agent turn; memory reads are a slice of that turn, the LLM call dominates (seconds).
- Per-layer read costs today: L4 exact-key SELECT, pooled since S29 (~1-5ms; pre-S29 it was
  2-3 fresh connects/turn); L5 hybrid retrieval **p95 48.4ms** @167 chunks (S12 gate) behind an
  **800ms driver deadline → governed found=false** (the only layer with a deadline today);
  L6 bounded newest-20 SELECT, flag-gated; L7 (planned) in-process cache + version bump (~0ms).
- **The pre-turn loads are SEQUENTIAL** (`openrouter.py` run_turn: merge → L4 load → L6 load →
  render), so worst cases add up instead of overlapping.
- S26 gave us `metric_event` counters but **no per-layer latency measurement** — today we cannot
  SEE a memory-latency regression except as vibes.

### Direction

**"用户无感" becomes a numbers contract, enforced by three disciplines already precedented:**

1. **Measure first (the S26 pattern):** per-layer read-latency emit (metric, duration_ms,
   fire-and-forget, eval-neutral) + p50/p95 tiles per layer on the metrics panel. No
   optimization before the histogram exists.
2. **A per-turn memory budget (the L5-deadline pattern, generalized):** every pre-turn layer
   read gets a deadline + fail-open skip (L5 already has it; L4/L6/L7 get cheap ones). Target
   SLO sketch: total pre-turn memory reads ≤150ms p95 — memory may degrade a reply's context,
   it may never stall the reply.
3. **Optimize only what the histogram indicts**, in this order: (a) parallelize the 3-4
   independent pre-turn loads (they share nothing until render); (b) batch onto one pooled
   connection; (c) cache read-mostly shared layers with version-bump invalidation (L7 by
   design; L6's confirmed set is a natural next). The S10 embedder-singleton and S29 pooling
   already killed the two historical hot spots — don't re-fix them.

### Draft slices
1. **S-L1 latency instrumentation + SLO tiles** — per-layer duration emits + metrics-panel
   p50/p95 + the written SLO. (S)
2. **S-L2 budget enforcement** — deadlines + fail-open on the non-L5 layers; parallel pre-turn
   loads IF the numbers say so. (S-M, gated on S-L1 evidence)

### Open questions
- SLO number: 150ms p95 for total pre-turn reads — right bar? (owner taste; cheap to move.)
- Parallelize with threads vs restructure to async — the turn runner is sync today; a thread
  pool for 3 reads is the ponytail answer.

---

## Candidate 3 — Admin memory-ops UX: one hub, one inbox, copilot-assisted triage

### Current facts (verified)

- Admin nav is already a **flat list of 8 single-purpose consoles** (Knowledge, Eval, Accounts,
  Memory Audit, Agent Experience, Metrics, Retention, Dead Letter) — it grows linearly with
  every slice, and "which console for which layer" is itself the scope-map question.
- Which layers actually need human maintenance (the honest inventory):

| Layer | Human maintenance? | Where today |
| --- | --- | --- |
| L1 identity | rare exceptions (mislink fixes — future) | simulator-gated link only |
| L2/L3 records | none (append-only; retention + dead-letter replay handle hygiene) | Retention / Dead Letter consoles |
| L4 customer memory | **exception-driven**: audit, attributed clear, rep corrections | Memory Audit console + copilot preferences panel |
| L5 knowledge | **content in Shopify** (established); ingest/probe/gates in admin | Knowledge console |
| L6 experience | **review queue**: Accept/Reject proposals | Agent Experience console |
| L7 lexicon (planned) | **review queue + manual CRUD** | (Candidate 1) |
| policy slots (outside) | eval-gated publish | Eval console |

  Pattern: **admins maintain by exception and by review queue — never by routine data entry.**
  The design goal is to make that pattern visible instead of scattered.

### Direction

1. **One "Memory" hub page** mirroring the L1-L7 map (the architecture diagram AS the UI): one
   row per layer — status, live counts (pending proposals, zero-hit entries, last ingest, last
   sweep, found-rate), one click into the existing console. New-admin learning cost collapses
   to "the hub is the mental model"; the 8 consoles stay as-is underneath (no rebuild — the hub
   is navigation + counts, ~1 read route reusing existing reads).
2. **One unified review inbox**: L6 + L7 pending proposals in a single queue with a layer badge
   per item, Accept / Edit / Reject / **Re-classify** (the anti-mis-filing action from
   Candidate 4). L4 proposals stay in the copilot per-case panel — they belong to reps in case
   context, not to the admin inbox. Daily workflow becomes: log in → inbox badge (N) → clear
   it → glance at hub counts → done.
3. **Copilot-assisted maintenance — advisory, never writing (the S27/judge posture):**
   - **Queue triage annotations**: a background copilot pass (the S23 fork pattern — internal
     infra, not a new LLM-callable surface) pre-reviews each pending proposal and annotates:
     likely-duplicate-of X / conflicts-with entry Y / PII-suspect / suggested canonical form +
     a recommend(approve|reject) with one-line reasoning. Rendered inline in the inbox; the
     ADMIN decides. Annotations ride a governed annotation field, framework-attributed.
   - **Natural-language manual add**: admin types "TOEE 也叫拓意" → copilot drafts the
     structured lexicon entry → **form pre-fill, admin confirms** — the copilot never writes a
     row directly.
   - Explicitly NOT chosen (records the security reasoning): a supervisor chat copilot with the
     admin-only read tools allowlisted. Those actions sit in `_AGENT_EXCLUDED_ACTIONS`
     precisely so cross-customer reads never enter an LLM tool loop; un-excluding them for a
     chat surface is a real prompt-injection surface for zero benefit the annotation pass
     doesn't already deliver. Revisit only with its own ADR.

### Draft slices
1. **S-U1 Memory hub** — hub page + counts read (reuses existing admin reads). (S)
2. **S-U2 unified inbox** — merged L6/L7 queue + re-classify action. (M, wants Candidate 1 S-A)
3. **S-U3 copilot triage annotations + NL manual-add pre-fill** — the fork-pattern annotator +
   form drafting. (M)

### Open questions
- Hub replaces the flat nav, or sits above it? (lean: sits above; consoles keep deep links.)
- Inbox digest OFF-workbench (email/Slack) — deferred until a real provider exists.
- Annotation model cost knob: annotate every proposal vs on-demand per item.

---

## Candidate 4 — Systemic anti-gap / anti-overlap: from documented boundaries to enforced ones

### The gap in the current answer

Candidate 1 records the routing tree and boundary pins **as documentation + process**. The
owner's requirement is *system-level* prevention: mis-filing and drift should be caught by
machines and routines, not by everyone remembering the map. Four enforcement tiers, cheapest
first — tiers 1 is built, 2-4 are the work:

**Tier 1 — structural exclusivity (already shipped):** one governed write tool per layer;
per-layer unique keys/tables; per-layer injection fences; single audit log with framework
attribution. A fact physically cannot enter two layers through the write paths.

**Tier 2 — tripwire tests (cheap, new):**
- A `LAYER_OF_ACTION` map in code (every memory-writing catalog action → exactly one layer
  table) + a completeness test: adding a write action without declaring its layer fails CI.
- An injection-composition test: the assembled system message carries at most one fence per
  layer and no unfenced memory content.
- The boundary matrix rows that are testable become tests (L5 corpus no-PII already has the
  S07 boundary-check report; L7 write scan rides the S22 scanner; L4 context-only binding
  already has the removal tripwire). Rows that are doc-only get marked as such — honesty over
  theater.

**Tier 3 — write-time advisory checks (rides existing machinery):**
- **Shape re-router**: `propose_experience` runs a cheap "is this lexicon-shaped?" heuristic
  (looks like `A = B` / `A means B`); if so, the proposal is annotated "consider re-filing to
  L7" (or auto-rerouted — owner taste). Deterministic heuristic, human decides — no prompt
  drift dependency.
- **Cross-layer dedup at propose time**: the handler checks existing L7 surfaces / L6 notes for
  the same surface form and annotates duplicates for the queue.

**Tier 4 — scheduled sweeps + queue actions (the S28 pattern):**
- **Graduation sweep**: a scheduled job that flags confirmed L6 notes matching the structurable
  shape → admin sees "graduate to L7?" items in the inbox. (The systemic anti-GAP: the free-text
  catch-all layer is routinely drained into the structured one.)
- **Re-classify** in the unified inbox (Candidate 3): mis-filed entries move between queues
  instead of being rejected and retyped. (The systemic anti-OVERLAP correction path.)
- **Zero-hit retirement report**: L7 hit counts + L6 injection usage on the metrics panel; dead
  vocabulary gets retired instead of accumulating as shadow-overlap.

### Draft slices
1. **S-G1 tripwire tests** — LAYER_OF_ACTION map + completeness + fence-composition tests +
   testable boundary rows. (S)
2. **S-G2 write-time advisories** — shape re-router + dedup annotations on both propose
   handlers. (S-M)
3. **S-G3 graduation sweep + retirement report** — scheduled job + inbox items + metrics tile.
   (M, wants Candidates 1+3)

### Open questions
- Auto-reroute vs annotate-only for lexicon-shaped L6 proposals (lean: annotate-only first —
  consistent with "human decides").
- Does the graduation sweep run on a schedule (S28 pattern) or fire on-confirm (event-driven)?

---

## Candidate slots 5+ — deliberately empty

0.0.4 (job queue, worker cutover, scoring mechanism, TS cleanup) is heavy and in flight.
Further 0.0.5 candidates land here only after 0.0.4 ships or an owner decision reprioritizes.
