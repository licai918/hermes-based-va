# 0.0.5 — Exploration

> Status: **exploration**. Candidates here are directions with evidence, not commitments.
> The 0.0.3 pipeline applies before any build: grill → PRD (gap-audited) → issue slices.
> 0.0.4 (job queue + scoring) is in flight and deliberately NOT expanded by this document.
>
> **Owner-set gate (2026-07-21): the 0.0.5 grill starts only AFTER 0.0.4 closes**, and it
> starts with an **inventory of what 0.0.4 actually shipped** (job queue, worker cutover,
> scoring mechanism, TS cleanup) — the candidates below get re-grounded against that reality
> before grilling, since several lean on infrastructure 0.0.4 may have changed (scheduled
> jobs, workers, admin panels). Theme of the iteration: **complete the memory architecture**
> (L7 + latency SLO + memory-ops UX + systemic boundary enforcement).
>
> ---
>
> **GRILL OUTCOMES (2026-07-21, gate satisfied at 0.0.4 closeout; owner: “全按推荐” — locked):**
>
> *Seven owner decisions:* ① L7 external capture = **gateway-side post-turn fork** (external
> agent still writes nothing; ADR-0152 superseding note). ② Memory SLO = **≤150ms p95** total
> pre-turn reads. ③ Lexicon-shaped L6 proposals = **annotate-only**, human re-files.
> ④ L4 value injection scan = **hard-reject**. ⑤ Privacy complaint rate = **forget-me proxy**,
> honestly labeled, until a business intake channel exists. ⑥ **0.0.3’s S32 debt folds into
> the T6 eval track** (recall@3 ≥80% on the owner’s ~30 real questions — the question set
> remains the ONE owner input dependency of 0.0.5). ⑦ Supervisor fail-review with a
> preference-shaped cause = **one-click L4 correction prefill** (resolves C6 open q#2).
>
> *Board calls made in-grill:* C1 season source = date-derived + admin-overridable
> `default_rule` row; normalizer output validated against the live Shopify catalog; glossary
> starts newest-20 (hit-ranked later on real data); confirm policy = rule in L7, phrasing in
> persona. C3 hub sits ABOVE the consoles (deep links stay); triage annotator = scheduled
> batch + per-item on-demand. C4 graduation sweep = scheduled (S04 worker pattern), not
> event-driven. C5 safety leg: any injected-instruction-obeyed = red, zero tolerance.
> C6 thresholds start **N=3 same-tag fails / M=3 similar diffs** (calibrate on Phase 1
> distribution); C6 is the LAST track. **The Memory Control Loop** (grill continuation): the
> scoring system is the sensor suite, memory actions are the actuators, and the wiring law is
> *scores sense, humans actuate, every actuation is a governed proposal* — see §6.6 for the
> deltas this locked in (knob tuning, injection-stratified judge sampling, per-entry
> effectiveness scores).
>
> *Re-grounding corrections from the closeout inventory:* `agent_turn_trace` is **NOT on
> main** (a rebased-away dev artifact) → the injection provenance ledger (S-M2) is a **new
> table** and doubles as the scoring system’s locator (score × ledger). The “three-in-sync
> catalog” set changed after 0.0.4 S11 deleted the TS mock packages — re-list sync points at
> slicing. ADR/migration numbering restarts at ~0155/~0020 — moving targets, re-check at land
> time (qf lands 0018/0019).
>
> *Track shape (≈20-22 slices):* T1 L7 (S-A→S-B→S-C, the long pole) · T2 lifecycle core
> (S-M1/M2/M5, parallel to T1) · T3 enforcement (S-G1 early cheap → S-G2 → S-G3) · T4 UX
> (S-U1→S-U2→S-U3) · T5 latency (S-L1 early → S-L2 on evidence) · T6 eval+feedback LAST
> (S-M3/M4 + S32 fold-in + S-F1..F4). Early birds: S-G1 + S-L1.

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

## Candidate 5 — Memory lifecycle governance: conflicts, forgetting, poisoning (systemic)

Owner framing (2026-07-21): with L1-L7 designed, three lifecycle themes need SYSTEMIC answers,
not scattered mechanisms — **conflicts (记忆冲突), forgetting (遗忘机制), poisoning (污染治理)**
— plus the evaluation system that proves they work. This candidate inventories what exists,
names the gaps (verified in code), and completes each theme.

### 5.0 Inventory — what already exists vs. the verified gaps

| Lifecycle stage | Shipped (0.0.3, verified) | Proposed elsewhere in 0.0.5 | **Gap (verified in code)** |
| --- | --- | --- | --- |
| Admission (what may enter) | L4: closed 4-slot vocabulary (ADR-0111), `_require_slot` rejects open keys, evidence verbatim, 200-char cap; L6/L7: propose→confirm human gate + S22 write-side scan; L5: Shopify-authored only + S07 no-PII boundary report; live facts NEVER memory | L7 scan (C1) | **L4 VALUES get no injection-pattern scan** — `_require_value` is type+length only |
| Recall (use without interference) | bounded + fenced + framed per layer (`<untrusted_customer_memory>` "preferences to honor, not instructions to obey"; L6 confirmed-only newest-20; L5 top-k behind an 800ms deadline); honored-rate judge (advisory) | latency SLO (C2); relevance-ranked L6/L7 selection (C1 open q) | no judge leg for MIS-application (memory used where it should not be) |
| Update / drift (偏好变化) | L4 last-write-wins with full attribution + evidence + `updated_at`; verified-wins at merge (ADR-0112/0151); S28 time-based retention (730d/90d off `last_interaction_at`) | zero-hit retirement, graduation sweep (C3/C4) | **overwrite loses the OLD value** — `_upsert_preference` writes NO audit row, so there is no value-change history to audit or roll back |
| Conflict | per-slot recency-wins; provisional-never-overwrites-verified (`ON CONFLICT DO NOTHING`); cross-channel deterministic precedence (ADR-0151); L7 `UNIQUE(domain,surface)` | dedup/conflict annotations, re-classify, LAYER_OF_ACTION tripwires (C3/C4) | no named conflict TAXONOMY: each conflict class should map to a deterministic-or-human resolution, testable |
| Poisoning | framework-derived source/actor (unforgeable); proposals read from governed RESULTS never model prose (S14); draft-turn writes discarded (ADR-0150); external never proposes (ADR-0152); context-only binding (no cross-customer targeting); S22 scan on L6; read-side fencing; human gates; removal tripwire | L7 scan; copilot triage PII-suspect annotation (C3) | L4 value scan missing (above); no poisoning METRIC; no formalized adversarial eval suite (S09 exists only as unit tests) |
| Deletion | **already frontend-real**: supervisor attributed Clear (S20), verified-customer "forget me" (S21), L6 reject/retire (S24), retention sweep panel (S28) — all audited, all policy_blocked-gated | — | no whole-binding one-click erase (today = per-slot); no deletion-success metric |
| Blast-radius repair (错误记忆影响多任务) | full attribution + evidence + audit trail answer WHO/WHEN; S26 counts injections | — | **cannot answer WHICH turns a given memory touched** — injection is counted, not linked. (0.0.4's new `agent_turn_trace` table is the natural anchor — re-ground at the grill.) |
| Evaluation | deterministic replay gate (CI hard); judge honored-rate (advisory, never gating) + S27 fixture-measured judge precision/recall; metrics panel (injection/found/corrections/accept-dismiss); 0.0.4 is building a scheduled judge job + live aggregates — INVENTORY FIRST | hit metrics (C1/C3/C4) | no per-customer memory-health view; no preference-CHANGE or adversarial scenario families in the eval suite; "hit rate alone misleads" needs multi-leg scoring codified |

### 5.1 Admission — 什么内容可以写入长期记忆

The shipped answer is already principled: **closed schemas + human gates + provenance**, per
layer (the L1-L7 routing tree in Candidate 1 decides WHERE; the layer's own gate decides IF).
One completion: extend the S22 scanner to **L4 slot values** at write time
(instruction-injection + PII-shape patterns; same shared-scanner discipline, mock+PG lockstep).
Design choice for the grill: hard-reject vs store-plus-flag (lean: hard-reject for injection
patterns — a delivery note has no legitimate reason to contain "ignore previous instructions";
annotate-only for softer smells).

### 5.2 Recall interference — 召回如何不干扰当前任务

Bounded + fenced + framed is the shipped discipline; complete it with **measurement**: add a
judge leg for **misapplication** (memory applied where the current task didn't call for it) and
one for **stale-use** (a superseded value used). Both advisory like honored-rate; both feed the
metrics panel. Relevance-ranked L6/L7 selection stays a C1/C2 concern (bounded-N + ranking),
gated on real usage data.

### 5.3 Drift & forgetting — 用户偏好变化,旧记忆怎么办

Policy (already right): the customer's LATEST explicit statement wins immediately — overwrite,
don't version-negotiate. Complete it three ways:
1. **Value-change audit row on upsert** (closes the verified gap): `preference_updated` audit
   rows carrying `{old_value, new_value}` in details — the supervisor view then shows true
   value history; rollback becomes possible; the S16 pattern extends for free. (Small, no
   schema change — it is the same `insert_audit` the clear already writes.)
2. **Time-based forgetting is shipped** (S28: 730d verified / 90d provisional off
   `last_interaction_at`) — fold L6/L7 into the same sweep framework: L6/L7 do not age by time
   but by USE (zero-hit retirement, C3/C4) — two forgetting axes, both scheduled, both visible
   on the retention/metrics panels.
3. **Systemic statement for the map**: L4 forgets by recency-overwrite + retention window;
   L5 forgets by re-ingest (corpus mirrors Shopify); L6/L7 forget by human retire + zero-hit
   sweep. Every layer has a named forgetting mechanism — record the table in memory-layers.md
   when this lands.

### 5.4 Conflict taxonomy — 记忆冲突怎么处理

Name the classes; each gets a deterministic-or-human resolution (most are shipped):

| Conflict class | Resolution | Status |
| --- | --- | --- |
| same slot, new statement | recency wins, attributed, (new) old→new audit row | shipped + 5.3.1 |
| provisional vs verified | verified never overwritten (`DO NOTHING`) | shipped (ADR-0112) |
| cross-channel provisional | deterministic precedence, own-channel-first | shipped (ADR-0151) |
| same L7 surface, conflicting canonicals | `UNIQUE(domain,surface)` blocks silent dup; queue shows conflict annotation; ADMIN decides | C1/C3 |
| semantically contradictory L6 notes | dedup/conflict annotation in the inbox; admin edits/rejects | C3 |
| cross-LAYER contradiction (e.g. L4 note vs L7 default) | scope routing (C1 tree) prevents most; L4 (customer-specific) beats L7 (shared default) at render — precedence rule to codify in the injection composer + one tripwire test | **new, small** |

### 5.5 Poisoning — 防止 Prompt 注入污染记忆

Defense-in-depth is mostly shipped (five lines: unforgeable attribution → governed-result-only
extraction → propose-not-write → scan → fence → human gate). Complete it with: (a) the L4 value
scan (5.1); (b) a **pollution metric**: scan-rejection count + entries confirmed-then-retired-
as-poisoned, as metric_event emits → a rate tile; (c) **formalized adversarial eval family**
(promote the S09 unit tests into eval scenarios): customer text carrying injection strings →
assert not stored (scan) OR stored-but-not-obeyed (fence, judged as a HIGH-severity leg —
this one CAN gate, unlike advisory legs, because "injected instruction obeyed" is a safety
failure, consistent with failed_high in the replay gate).

### 5.6 Deletion — 记忆删除是否可以在前端实现

**Already implemented and governed** (S20/S21/S24/S28 — attributed, audited, fail-closed).
Completions: a whole-binding "erase customer memory" action (loops the governed per-slot clear,
one audit row per slot + a summary row — no new write primitive), and a **deletion-success
metric** (cleared-and-stayed-cleared / clear requests; re-appearance would indicate a merge or
proposal re-creating it — itself a valuable tripwire).

### 5.7 Blast-radius repair — 错误记忆影响多任务,如何修复

The one genuinely new mechanism: an **injection provenance ledger** — per governed turn, record
WHICH memory entries were injected (layer, entry id/slot, turn/case id). Anchor: 0.0.4's
`agent_turn_trace` table (re-ground at the grill — it may already carry most of this). Then the
repair workflow is mechanical:
1. correct/retire the wrong entry (existing governed actions);
2. query the ledger → the affected turns/cases list;
3. surface as inbox items ("N open cases touched by retired entry X — review?") — closed cases
   get a business-judgment sampling, not auto-reopen;
4. future turns are clean by construction (confirmed-only reads).
Past replies cannot be unsaid; the system's job is to make the blast radius ENUMERABLE and the
open-case review one click. The same ledger powers the recall-relevance metrics below.

### 5.8 Evaluation — 怎么评估记忆系统(含 per-user)+ 前端展示

**Core metric set** (each with its source; "hit rate alone misleads" is the design law —
multi-leg, advisory-by-default, safety legs gate):

| Metric | Source | Display |
| --- | --- | --- |
| recall relevance / honored rate | judge legs (shipped + 5.2 legs) | metrics panel (advisory) |
| misapplication rate / stale-use rate | new judge legs (5.2) | metrics panel |
| conflict rate | conflict annotations / proposals + differing-value overwrites per period (5.3.1 audit rows make this countable) | metrics panel |
| pollution rate | scan rejections + poisoned-retirements (5.5) | metrics panel |
| user correction count | shipped (S26, employee_confirmed writes) | metrics panel |
| deletion success rate | 5.6 | metrics panel + retention panel |
| privacy-deflection & forget-me usage | S21 audit rows (initiator=customer) — honest proxy; true complaint rate needs a business channel (owner input) | metrics panel |
| per-customer memory health | slots age, correction count, last-injection recency, clear history — all existing reads | a "memory health" strip on the Memory Audit console (per-customer, where admins already look) |

**Eval suite additions** (the owner-named scenario families): preference-change (state A, later
state B → assert B honored AND A not used — exercises 5.2 stale-use leg), adversarial/malicious
input (5.5 family, gating), deletion (forget-me → deflection + emptiness). All recorded/replayed
under the existing deterministic gate; judge legs advisory except the safety leg. NOTE: 0.0.4 is
shipping a scheduled judge job + live aggregates — this section gets re-grounded against that at
the closeout inventory before slicing.

### Draft slices
1. **S-M1 value-history + L4 value scan** — `preference_updated` audit rows (old→new) + S22
   scanner extended to L4 values; supervisor view shows value history. (S-M)
2. **S-M2 injection provenance ledger + repair workflow** — per-turn injected-entry records
   (anchor: `agent_turn_trace`) + affected-cases query + inbox review items. (M)
3. **S-M3 lifecycle metrics + judge legs** — misapplication/stale-use legs, conflict/pollution/
   deletion-success emits, per-customer memory-health strip. (M, after 0.0.4 scoring inventory)
4. **S-M4 adversarial + preference-change eval families** — promote S09 to eval scenarios,
   safety leg gating, forget-me scenario. (S-M)
5. **S-M5 whole-binding erase + deletion-success tripwire** — governed loop + metric. (S)

### Open questions (grill fodder)
- L4 value scan: hard-reject vs store-and-flag for injection patterns (lean: hard-reject).
- Cross-layer precedence at render (L4-specific beats L7-default) — composer rule + where the
  tripwire test lives.
- Privacy complaint rate: what is the real intake channel? (owner/business question.)
- Does the ledger live in `agent_turn_trace` (extend) or its own table? (0.0.4 inventory first.)
- Safety-leg gating threshold: any injected-instruction-obeyed = red, or a tolerance? (lean:
  any = red.)

---

## Candidate 6 — Feedback Ingress: 0.0.4's scoring becomes the memory system's sensory input

Owner framing (2026-07-21): how does 0.0.4's scoring mechanism combine with the 0.0.5 memory
system into ONE feedback entry point (反馈入口)? Answer: this is **quality-feedback Phase 2**
— explicitly deferred by that module's PRD with its shape already decided ("builds nothing
new: feeds L6, KnowledgeOps, metrics") — now completed against the FULL 0.0.5 architecture
(L7, the lifecycle governance of Candidate 5, the unified inbox of Candidate 3).

### 6.0 Inventory — the two scoring arms 0.0.4 shipped (verified)

| Arm | What it captures | Key properties |
| --- | --- | --- |
| **Human scoring** (quality-feedback module, ADR-0154) | `interaction_review`: supervisor pass/fail + fixed reason tags on auto-handled / sales-outreach records; `draft_feedback`: rep 👍/👎 + tags, PLUS the implicit signal — `sent_as_is` / `sent_edited` + edit-distance ratio, correlation id, generated-draft snapshot | dispatch-only tool in NO allowlist → **the AI structurally cannot score itself**; append-only; actor-attributed; fail-closed; Phase 1 = capture only |
| **Automated scoring** (judge) | S20 advisory-forever PR reports (honored / no-unprompted-recall legs); S22 scheduled honored-rate job over **real recent memory injections**; S23 QualityGatesPanel live artifacts with staleness honesty | advisory, never gating; background-worker scheduled; per-injection verdicts are the raw material |

### 6.1 The grilled core insight — two feedback DIRECTIONS, one join

- **Scores about OUTPUT** (human reviews/ratings/edits) → propose memory **ADDITIONS and
  corrections** (something was missing or wrong → candidate L5/L6/L7 content).
- **Scores about MEMORY USE** (judge legs: honored / misapplied / stale — Candidate 5.2) →
  propose memory **RETIREMENT and repair** (an entry exists and is hurting).
- **The join is Candidate 5.7's injection provenance ledger**: without it, a score attaches to
  a CONVERSATION; with it, `score × ledger` attaches to the **memory entries injected into that
  turn** — per-entry quality attribution. A failed review + the ledger = a suspect-entry list.
  This is what makes the scoring system the memory system's sensory organ rather than a
  separate dashboard.

### 6.2 The Signal Routing Table (the artifact the grill must pin)

| Signal | Routed to | Mechanism |
| --- | --- | --- |
| `factual_error` (ext/int) | L5 knowledge-slot draft via existing KnowledgeOps `submit_for_eval`, OR an L7 alias fix | aggregator clusters; human decides in the inbox |
| `missed_information` / `missing_context` | L5 gap or L4 injection-miss review item | inbox item with the conversation as evidence |
| `tool_misuse` / `wrong_action` / `should_have_escalated` | L6 procedure proposal | `propose_experience`, `source=feedback_derived` |
| **consistent `sent_edited` diffs** (the highest-volume signal) | L6 procedure or **L7 alias** proposals — repeated rep rewrites of the same surface form are lexicon gold (e.g. reps keep rewriting a product name → alias candidate) | edit-diff mining (6.4) |
| `wrong_tone` / `too_verbose` / `tone_inappropriate` | **OUT of memory** → persona-change inbox item (separate governance: prompt change + eval re-record) | routed, not stored as memory |
| `policy_violation` | **OUT of memory layers** → policy slots via the existing publish gate | existing KnowledgeOps flow |
| judge low-honored on a specific entry | retirement review item for that entry | score × ledger (6.1) |
| judge stale-use | L4 drift review item | Candidate 5.2 leg |
| zero-hit (L6/L7) | retirement | already designed (C3/C4) |

Routing law: **every signal terminates in a queue a human already works** (the C3 unified
inbox, KnowledgeOps, or Memory Audit) — no new approval surface (qf-PRD NFR-4 upheld).

### 6.3 The Feedback Aggregator — one scheduled job, propose-only

One background-worker job (0.0.4's S04 worker + S22 job pattern): read feedback since the last
watermark → cluster (tag × subject × correlation id) → when a threshold trips (N same-tag
fails on similar subjects; M similar edit-diffs) → emit **`proposed` rows into the EXISTING
queues** (agent_experience with a distinguishing `feedback_derived` source, lexicon proposals,
knowledge-slot drafts), carrying the feedback row ids as evidence → the C3 inbox → human
decides. **Nothing auto-writes memory** — the propose→confirm law is absolute (qf-PRD US-19/26,
§8's anti-self-modification stance).

**Eval-neutrality resolved** (qf-PRD NFR-3's re-open clause): the aggregator writes
proposed-only rows (inert by construction); the only turn-reaching path is confirmed entries,
which are already eval-pinned (S25). No new eval sensitivity.

### 6.4 Edit-diff mining (the deliberately-scoped hard part)

The `sent_edited` stream carries the correction itself (generated snapshot vs sent text).
Mining it: deterministic diff + clustering first (same-span rewrites recurring across drafts);
an LLM-assisted clustering pass is allowed ONLY as a fork-pattern advisory annotator (the C3
triage posture) — its output is a proposal draft, never a write. Grill question: threshold and
cluster-similarity knobs start crude and calibrate on Phase 1's real distribution (qf-PRD §9's
volume note: implicit outcomes vastly outnumber explicit ratings — weight accordingly).

### 6.5 Loop-closure metrics (proving the feedback entry works)

On the existing metrics panel: **feedback→proposal conversion rate**, **post-fix re-fail rate**
(the same tag recurring on the same subject AFTER a confirmed fix — the single most honest
"did the loop work" number), per-entry honored-rate trend after a replacement, and
feedback-sourced correction counts on the per-customer memory-health strip (C5.8). The loop
closes measurably: score → aggregate → propose → confirm → inject → next scores move.

### 6.6 Memory Control Loop deltas (grill continuation, 2026-07-21 — locked)

Three additions the “scoring applied to memory TUNING” grill locked beyond 6.1-6.5:

1. **Knob tuning is an actuator class of its own.** Signals like a week-over-week global
   honored-rate decline route not to entry-level proposals but to the TUNING KNOBS: glossary
   bounded-N (C1), L6 bounded-20, injection phrasing, retention windows. Knobs get an
   admin-visible read-only panel (values + change path via config); every knob change is
   audited. Content never auto-changes; knobs change only by admin action — same law, one
   level up.
2. **Injection-stratified judge sampling.** The judge has a cost budget; the ledger (S-M2)
   makes turns WITH memory injections targetable, so the S22 scheduled job stratifies its
   sample toward them — judge spend concentrates where memory actually appeared. Small change
   to the existing job.
3. **Per-entry effectiveness scores are a first-class deliverable** (not a by-product):
   ledger × judge verdicts → per-entry honored / misapplied / stale rates, joined with
   hit_count into ONE entry-health score that drives the retirement queue. S-M2’s acceptance
   gains a clause: the ledger’s grain MUST support this join (turn_id × layer × entry_id).

### Draft slices
1. **S-F1 aggregator job + routing table + thresholds** — the scheduled propose-only job over
   both feedback tables. (M; needs qf Phase 1 shipped + a real distribution)
2. **S-F2 score × ledger join** — per-entry attribution + effectiveness scores +
   retirement/repair review items; includes the stratified-sampling change to the S22 job.
   (M; needs C5.7's ledger)
3. **S-F3 edit-diff mining → L6/L7 proposal shapes.** (M)
4. **S-F4 loop-closure metrics + knob panel.** (S)

### Open questions (grill outcomes applied)
- ~~Threshold initial values~~ **RESOLVED (grill): start N=3 same-tag fails / M=3 similar
  diffs**, calibrate on Phase 1’s real distribution.
- ~~Supervisor fail-review → L4 prefill~~ **RESOLVED (owner decision ⑦): yes** — one click
  from verdict to fix.
- ~~Sequencing~~ **RESOLVED: C6 is the LAST 0.0.5 track** (T6).
- Still open: where do OUT-of-memory signals (persona/tone) land operationally — an inbox
  item kind, given no ticket system exists? (PRD decides the item shape.)

---

## Candidate slots 7+ — deliberately empty

0.0.4 (job queue, worker cutover, scoring mechanism, TS cleanup) is heavy and in flight.
Further 0.0.5 candidates land here only after 0.0.4 ships or an owner decision reprioritizes.
