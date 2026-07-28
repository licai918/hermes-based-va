# Memory architecture — layer map

**What this is.** The **current-state structural view** of the Hermes VA's memory: what each
layer holds, where it physically lives, how it is retrieved, how it is governed, and which ADRs
decide it.

**What this is NOT.** Not a glossary — that is [`CONTEXT.md`](../../CONTEXT.md). Not a decision
record — those are [`docs/adr/`](../adr/). This file **links** rather than restates, deliberately,
so it cannot drift out of sync with them.

> **Maintenance rule.** When an ADR lands that changes a layer, update that layer's row **in the
> same PR**. No separate doc-maintenance ritual — the ADR is the trigger.

*Last updated: 2026-07-28 (0.0.5 S06 — L7 semantic lexicon shipped; the L1–L7 routing
decision tree and the L7 boundary rows land here).*

---

## At a glance

| # | Layer | Holds | Physically | Retrieval | Status |
| --- | --- | --- | --- | --- | --- |
| **L1** | Identity Graph | channel identities, identity snapshots, Shopify/cross-system links, consent (SMS Opt-Out), match history | `toee_va` Postgres | exact key (phone / email → identity) | ✅ shipped |
| **L2** | Conversation | Customer Thread, Email Thread, SMS Session windows, MessageTurn, AgentTurnContext | `toee_va` Postgres | keyed by thread / session id | ✅ shipped |
| **L3** | Operational | Follow-up Case, Workbench Audit Log, auto-handled evidence, eval records | `toee_va` Postgres | keyed / queried per workflow | ✅ shipped |
| **L4** | Customer Memory | 4 governed preference slots per customer | `toee_va` Postgres | **exact** `WHERE binding_key = ?`, injected per turn | ✅ shipped (0.0.1 + 0.0.2) |
| **L5** | **Knowledge** | shared, non-PII company/product corpus | **separate `toee_knowledge` DB** | **hybrid lexical FTS + dense embedding**, top-k chunks | ✅ **shipped** ([ADR-0149](../adr/0149-hybrid-lexical-embedding-knowledge-retriever.md)) |
| **L6** | **Agent experience** | what the agent learns from doing the job (operational, non-PII) | `toee_va` Postgres (`agent_experience`) | confirmed-only, bounded newest-first, injected per gated turn | ✅ **shipped** ([ADR-0152](../adr/0152-l6-agent-experience-confirmed-injection-and-eval-pin.md)) |
| **L7** | **Semantic lexicon** | domain language: surface→canonical aliases, notation normalizers, contextual defaults (shared, non-PII) | `toee_va` Postgres (`semantic_lexicon`) | **deterministic param normalization (hard)** + confirmed-only, bounded newest-20 `<confirmed_lexicon>` glossary per gated turn (soft) | ✅ **shipped** ([ADR-0161](../adr/0161-l7-semantic-lexicon-governed-domain-language-and-its-two-seams.md)) |

L1–L4 are the **four-layer model** of [ADR-0110](../adr/0110-native-memory-four-layer-model.md).
L5 (Knowledge) and L6 (Agent experience) are the 0.0.3 additions; L7 (Semantic lexicon) is the
0.0.5 addition. All three are now shipped — see below.

The same Postgres also holds **Workbench Accounts**, **knowledge publish state** (the 6
governed operational-policy slots + history), and the **ADR-0154 quality-feedback stores**
(`interaction_review`, `draft_feedback`). Those sit **outside** the seven-layer model — see
[Outside the layer model](#outside-the-layer-model-and-why) for why, and for the rule that
decides it.

---

## Routing — which layer owns a fact

Every branch terminates, which is the point: a branch that ran out of options would be a gap,
and a fact with two homes would be an overlap. From
[the 0.0.5 exploration](../../workspace/0.0.5/EXPLORATION.md).

```
Is it about ONE customer?
├─ yes → identity link? L1 | the words themselves? L2 | a case/action? L3 | a preference/habit? L4
├─ no — is it a LIVE business fact (price/stock/order/AR)? → tool read; forbidden in every layer
└─ no — shared & static →
   ├─ expressible as surface→canonical or a structured rule ("X means Y")? → L7
   ├─ prose fact a customer would ask, answer belongs on the website? → L5 (edit Shopify)
   └─ only expressible as a how-to paragraph? → L6  ← the catch-all shape
```

**The three easiest-to-blur boundaries:**

- **L6 vs L7** — if it CAN be structured it MUST be L7; only what can't stays L6.
- **L5 vs L7** — L5 owns CONTENT ("what to know about 205/55R16": prose, retrievable, *may*
  miss); L7 owns LANGUAGE ("2055516 IS 205/55R16": a mapping, must *not* miss). They compose:
  normalize first (L7), retrieve second (L5).
- **L4 vs L7** — SCOPE decides, not shape. "Customers write sizes as 2055516" is shared
  language → L7. "THIS customer's 'the usual spot' means his side gate" is single-customer
  semantics → L4.

Scope decides which layer OWNS a fact. When two layers both speak on one turn, **precedence**
decides which wins — see the L7 section below.

---

## L1–L4 — the shipped four layers

**Substrate.** The **Toee Business Datastore** (Postgres) is the system of record
([ADR-0140](../adr/0140-business-datastore-system-of-record-hermes-memory-conversation-only.md)),
local-first ([ADR-0142](../adr/0142-local-first-datastore-and-per-profile-api-servers-cloud-deferred.md)).
ADR-0110's original substrate (Hermes Native Memory) is superseded; the layer model itself holds.

**L4 Customer Memory** is the one with governance machinery, so it is worth spelling out:
- Slots + binding + write sources: [ADR-0111](../adr/0111-customer-memory-slots-and-write-sources.md);
  provisional→verified merge: [ADR-0112](../adr/0112-provisional-customer-memory-merge-on-verified-ingress.md);
  per-turn injection: [ADR-0113](../adr/0113-customer-memory-lightweight-injection-reads.md);
  tool actions: [ADR-0114](../adr/0114-toee-customer-memory-v1-actions.md);
  retention: [ADR-0116](../adr/0116-conversation-and-customer-memory-retention.md).
- **Write attribution** (0.0.2): every write carries an honest `source`
  (`customer_explicit` / `employee_confirmed` / `copilot_agent` / `merged_provisional`) plus the
  acting rep in `actor_account_id` — framework-derived, never model-supplied.
  See [ADR-0148](../adr/0148-copilot-agent-source-actor-attribution-and-context-only-binding.md).
- **`copilot_agent` is history/vocabulary-only in production** (0.0.3 S13, the S20
  reversal): the copilot draft turn's `toee_customer_memory` write overlay is gone —
  an agent-initiated write during a draft always lands on the shared mock driver and
  is discarded, never Postgres. The draft turn *proposes* instead (structured
  `proposals[]`, Workbench Accept/Dismiss); an accepted proposal persists through the
  existing UI correction path (`employee_confirmed`), same as always. The resolver
  mapping and the `copilot_agent` enum value are unchanged (historical rows keep their
  meaning); only the production write path that could reach it is removed. See
  [ADR-0150](../adr/0150-s20-reversal-copilot-draft-turn-propose-only.md).
- **Cross-channel merge** (0.0.3 S19): a verified turn merges provisional slots
  from *every* channel identity linked to that customer (`identity_link`), not
  just the current turn's channel — the SMS→email continuity path. Precedence
  (this turn's own channel first, then linked channels in a fixed order) and
  the channel↔channel / verified↔verified dispositions are recorded in
  [ADR-0151](../adr/0151-cross-channel-provisional-merge-precedence.md), which
  supersedes ADR-0112's v1 "cross-channel out of scope" non-goal; ADR-0112's
  merge trigger/behavior and the never-overwrite-verified invariant hold.
- **Whole-binding erase** (0.0.5 S11, FR-13/US7): one governed
  `toee_customer_memory.erase_customer_memory` action loops the existing per-slot clear over
  the four slots, writing per-slot audit rows plus one summary row per binding. It clears the
  verified binding **and every linked channel identity's provisional binding**, because the
  cross-channel merge above would otherwise copy the provisional slots straight back on the
  customer's next verified turn. Admin-only and fail-closed: no attributed administrator, no
  erase, nothing deleted. It removes L4 **content** only — `injection_ledger` and
  `customer_memory_merge_audit` carry the same binding key but hold provenance (which slot
  *name* reached which turn, which keys were merged) and no slot value, and the erase's own
  acceptance is that it leaves a *complete* audit trail. Cleared-and-stayed-cleared is watched
  by the FR-14 deletion-success tripwire, a deterministic query over the summary rows and
  `customer_memory_slot`; it flags both a row the erase left behind and one written afterwards,
  inside a named 30-day window, and it proposes nothing — an alert for a human, never an
  automatic re-delete.
- Reads are **exact-key**, not semantic. There is no similarity search anywhere in L1–L4.

---

## L5 — Knowledge layer *(shipped — [ADR-0149](../adr/0149-hybrid-lexical-embedding-knowledge-retriever.md))*

**Decision: Path Y-embed, hybrid** — an in-house retriever fusing **lexical FTS + dense
embeddings**, indexed in a **separate database** that carries no PII, injected through the same
`extra_drivers` driver seam L4 uses. **gbrain (Path X) was evaluated and rejected** as
over-engineering for a curated FAQ-sized corpus. Formal decision record, isolation rationale,
deadline requirement, and the FR-2 authoring/review-gate open question:
[ADR-0149](../adr/0149-hybrid-lexical-embedding-knowledge-retriever.md).

Grounded in the 0.0.3 spike — see [`workspace/0.0.3/knowledge-spike/`](../../workspace/0.0.3/knowledge-spike/)
and Candidate 1 of [the 0.0.3 exploration](../../workspace/0.0.3/EXPLORATION.md):

| Gate | Result |
| --- | --- |
| **Isolation** | ✅ separate `toee_knowledge` DB + `knowledge_chunk`; business DB untouched |
| **Latency (spike, FTS-only rung — since corrected)** | FTS p95 **1.4 ms** @1500 chunks; forced 2 s query → governed `found=false` in 201 ms. Audit finding 1: this measured the **rejected** lexical-only rung, not the shipped hybrid one. |
| **Latency (S12 gate, shipped hybrid rung, `gates.py latency`)** | ✅ p95 **48.4 ms** @167 chunks (embedding inference included) — PASS vs. the 800ms bar; forced-slow path → governed `found=false` in 815 ms via the **driver-side deadline** (required, since no tool-call timeout exists in-repo). See [ADR-0149](../adr/0149-hybrid-lexical-embedding-knowledge-retriever.md). |
| **Quality (S12 gate, `gates.py recall`, 30 synthetic questions)** | 🟡 recall@3 **73%** (22/30) — below the 80% bar; interim dev-time gate. **The real ~30 owner-question gate is S32.** |

**Boundary:** knowledge is a shared, non-PII corpus — never live facts (Shopify/QBO tool reads),
never the governed policy-slot copy, never customer PII.

**Corpus source is settled:** the **Shopify connector** (pages, blog articles, shop policies) —
that is where the content already lives and where staff already author it; the spike pulled its
whole corpus from there. Gaps are closed by editing Shopify, not by crawling — see
[CONTENT-GAPS.md](../../workspace/0.0.3/knowledge-spike/CONTENT-GAPS.md).

**Still open:** the ongoing *refresh + authoring* flow and **where the review gate lives** — a
Shopify sync has no PR review, whereas a `brain/` git-PR flow does; a hybrid (Shopify for
existing pages, `brain/` for net-new authored knowledge) is possible. Recorded as an explicit open
question in [ADR-0149](../adr/0149-hybrid-lexical-embedding-knowledge-retriever.md) (FR-2), not
silently decided. Also open: embedding model, and short-doc handling (200-char Contact and thin
brand pages under-retrieve) — both S32 territory.

**Supersedes in practice:** the never-built weekly RAG / crawl / sync mechanisms of ADR-0001,
ADR-0002, ADR-0030 and ADR-0031 (their live-facts rules still hold). Formally recorded in
[ADR-0149](../adr/0149-hybrid-lexical-embedding-knowledge-retriever.md), which also ships the
checked-in FR-7/FR-7b quality/latency gates harness (`hermes_runtime/knowledge/gates.py`).

---

## L6 — Agent-experience memory *(shipped)*

*What the agent learns from doing the job* — distinct from customer PII (L4), authored corpus
(L5), and behaviour contract (`persona.py`). Candidate 8 of
[the 0.0.3 exploration](../../workspace/0.0.3/EXPLORATION.md).

**Shipped (0.0.3):** one governed `agent_experience` store, `kind`-tagged
(note|procedure), gated **propose → confirm → inject**. The copilot review fork
proposes (S23, `AGENT_EXPERIENCE_LEARNING`); an admin Accept/Reject confirms
(S24); only `status='confirmed'` entries are injected — into the copilot draft
turn (`AGENT_EXPERIENCE_INJECTION`) and, read-only, into the external turn
(`AGENT_EXPERIENCE_EXTERNAL_INJECTION`), two independent flags, both default OFF.
`proposed`/`rejected` are never injected; the read is operational-only (no
customer binding), bounded newest-first, fenced as human-approved guidance, and
fail-closed (a turn never fails on L6). L6 injection is pinned OFF on the
eval/record/replay path so the determinism gate stays green. Real-traffic cap /
ranking calibration is a deferred post-launch follow-up.
[ADR-0152](../adr/0152-l6-agent-experience-confirmed-injection-and-eval-pin.md).

**Scope check:** ADR-0111/0140 rejected Hermes built-in memory **as the store for customer
business records**. They say nothing about the agent accumulating its own operational
experience — L6 is that gap, a new layer, not a re-litigation.

**Design realized:** copies Hermes's *learning loop* (the background self-improvement
review fork), not its *store* — proposed learnings route through our governed
tool → Postgres → audit, gated **propose → confirm**, on the internal copilot where reps
already review every draft. Hermes native memory stays off (`skip_memory=True`); this is a
net-new governed retention surface, not the built-in store.

**Risks and how they were handled:** model-authored PII → the S22 write-side scan +
the S23 review prompt's operational-only rule + the S24 human confirm gate (three lines of
defense); unbounded transcript retention → bounded newest-first read, retention sweep (S28);
**cross-profile recall crossing the EXTERNAL/INTERNAL/SUPERVISOR boundary** → the external
turn is read-only over confirmed entries behind its own flag, never proposing, and
`toee_agent_experience` is INTERNAL-allowlisted only; poisoned-memory blast radius → nothing
injects until a human confirms, and only `status='confirmed'` is ever read; eval determinism →
injection pinned OFF on the record/replay path (both flags default off; the eval store can't
surface L6 even with flags forced on). Remaining: real-traffic quality/ranking calibration,
deferred post-launch (ADR-0152).

---

## L7 — Semantic lexicon *(shipped)*

*What the company's words mean* — domain language as governed data, distinct from customer
preferences (L4), prose facts (L5), and how-to guidance (L6). Motivating examples:
`TOEE ≡ TOEE TIRE`; `2055516 → 205/55R16`; a bare size defaults to the current season's tire
**with mandatory confirmation**. New product lines keep adding vocabulary, so routine entries
are admin-editable without a deploy, and the layer grows from conversations: a
customer-confirmed clarification ("do you mean 205/55R16?" → "yes") becomes a `proposed` entry
an admin approves/edits/rejects — the L6 propose→confirm pattern re-instantiated over a
**structured** store ("port the loop, not the store", again).

**Shipped (0.0.5):** one governed `semantic_lexicon` store with three entry kinds graded by
determinism (admin-free `alias` rows, code-owned `normalizer` patterns toggled per domain by
the row's `status`, structured `default_rule` rows), gated **propose → confirm → apply**, and
applied at **two seams**:

| Seam | What it does | Failure mode |
| --- | --- | --- |
| Tool-parameter normalization (**hard**) | rewrites a parameter, verified against the live catalog before anything is asserted | must not miss |
| `<confirmed_lexicon>` prompt glossary (**soft**) | puts confirmed vocabulary in front of the model, read-only and advisory | may miss; never asserts |

Only `status='confirmed'` entries are ever applied or injected — checked at the store read and
re-checked at render. The glossary is bounded to `LEXICON_GLOSSARY_LIMIT` (20) entries, fenced,
fail-closed (a turn never fails on L7), and injected into the copilot draft turn
(`LEXICON_INJECTION`) and, read-only, the external turn (`LEXICON_EXTERNAL_INJECTION`) — **two
independent flags, both default OFF**, which is also the eval-determinism pin.
[ADR-0161](../adr/0161-l7-semantic-lexicon-governed-domain-language-and-its-two-seams.md).

**A default is a question, not an assumption.** `default_rule` conditions are evaluated **at
render**: `current_season()` picks which seasonal rule applies and a confirmed `season=override`
row beats the calendar, so at most one seasonal line renders and it is phrased as an imperative
*ASK*, never a statement. The confirm posture is unswitchable in data (`confirm_required` is a
read-only property that is always `True`) and unbranched in rendering.

**Cross-layer precedence: L4 beats L7.** A customer's own stated preference outranks a shared
seasonal default — not "usually". Composition order is L1 snapshot → **L4** → L6 → **L7**, so
the glossary arrives after the customer's own words are established, and the glossary header
says so in words (*"the customer's own stated preferences take precedence over every line
below"*). Both mechanisms are tripwire-tested; either alone is a coin flip on how a model reads
a prompt. "In winter a bare size means winter tires" is a **default**, and a default that
overrides what the customer actually told you is a bug that reads as a feature.

**Risks and how they were handled:** model-authored PII → the S01 write-side split scan
(injection everywhere; PII redacted in place on `evidence`/`proposer_context`, never applied to
the digit-shaped `surface_form`) + the S02 human confirm gate; a bad admin-typed regex → the
regex lives in CODE, the row is only the per-domain toggle; poisoned vocabulary blast radius →
nothing applies until a human confirms, and only `confirmed` is ever read; a fence-closing
value → escaped at render on every layer (D19, below); eval determinism → both flags default
OFF and the record path structurally cannot read L7. Remaining: the real-traffic bound
calibration.

**Which 20 entries fill the bound is a knob (0.0.5 S26, FR-6's upgrade clause).**
`LEXICON_SELECTION` selects `newest` (the default — newest-decided first, unchanged) or
`health`, which ranks by the FR-31 entry-health score. Flipping it is a deploy-time config
commit, audited by git history like every other 0.0.5 knob (D14). It exists because
newest-first has a **silent** failure: past 20 confirmed entries a seasonal `default_rule` is
evicted by date and the agent simply stops asking the confirm-first question, with no error
anywhere. Ranking on usage alone would make that worse rather than better — `hit_count` counts
deterministic-seam applications, which are only ever aliases and normalizers, so a
`default_rule` earns **structurally zero** hits — so the ranked strategy fills the window
round-robin across entry kinds. Rarity by design is not uselessness.

**Per-entry effectiveness (0.0.5 S26, FR-31)** joins the S09 injection ledger to per-turn judge
verdicts (`judged_turn`) and materializes one row per entry in `entry_effectiveness`, refreshed
on the ledger's own prune tick. Every rate ships with its denominator and an unscored leg reports
`null`, never `0`. Two scopes travel with the score as **data**, not prose: it covers the
**external turn only** (the copilot draft path's `turn_ref` is synthetic, so its injections are
recorded and never attributed — D4.3), and attribution is **per turn**, so every entry in a
prompt shares that reply's verdict.

---

## Hermes Native Memory — where it actually sits

The upstream framework has its **own** memory (agent notes + an FTS5 transcript store +
an optional provider plugin + a background review fork + a skill library). Per
[ADR-0140](../adr/0140-business-datastore-system-of-record-hermes-memory-conversation-only.md)
it is **conversation-only and never a business system of record**.

**Today it is entirely off**: the runtime constructs the agent with `skip_memory=True` and points
`HERMES_HOME` at a per-process temp dir, so nothing accumulates between turns. Any adoption
(L6) is therefore a **net-new** retention surface — which is exactly why the governance can be
designed in up front rather than retrofitted.

> ⚠️ **Naming collision.** Our `memory_enabled()` (`hermes-runtime/.../tool_backend.py`) means
> **Customer Memory (L4)** — is the Postgres datastore backend active. Hermes's
> `memory.memory_enabled` config means **agent notes**. Different concepts; do not wire one
> expecting the other.

---

## Boundaries — what must never mix

| This | never holds | it lives in |
| --- | --- | --- |
| Knowledge (L5) | live price / stock / order / AR facts | real-time Shopify/QBO tool reads |
| Knowledge (L5) | the governed operational-policy copy | the 6 eval-gated policy slots |
| Knowledge (L5) | customer PII | Customer Memory (L4) |
| Customer Memory (L4) | live facts, policy text, consent state | tools / policy slots / Identity Graph (L1) |
| **Semantic lexicon (L7)** | **customer PII** | Customer Memory (L4) |
| **Semantic lexicon (L7)** | **live price / stock / order / AR facts** | real-time Shopify/QBO tool reads |
| **Semantic lexicon (L7)** | **single-customer semantics** ("*his* usual spot") | Customer Memory (L4) — scope decides, not shape |
| Any layer | model-supplied write attribution | `source` + `actor_account_id` are framework-derived |

**Machine-checked half (0.0.5 S12/S06, FR-15/16/17).** `toee_hermes/memory_layers.py`'s
`LAYER_OF_ACTION` declares, for **every** catalog action, the layer it writes — or `None` when it
writes no memory-layer content. `hermes-runtime/tests/test_memory_boundary_tripwires.py` asserts
that map against the catalog in both directions (an undeclared new action fails CI), asserts the
injection composition (≤1 fence per layer, no memory content outside a fence, **L4 before L7**,
and **no layer's own content can close its fence**), and turns the matrix rows above into tests.
Its docstring is the honest ledger of which rows are asserted there, which are asserted
elsewhere, and which remain **doc-only** — read it before assuming a row is enforced.

**A fence survives its own body (0.0.5 S06, D19).** A memory value containing one of the
injection fences' own closing tokens used to close that fence early, putting the rest of the
value in the same unfenced region as the framework-derived Session Identity Snapshot — a
*structural* prompt-injection escape that no "ignore previous instructions" pattern catches.
Closed on both sides: the write scan hard-rejects those tokens on **every** fenced layer — L6/L7
since 0.0.5 S01, L4 since **0.0.5 S08** (FR-10), which closed the reachable half, since a slot
value is the one an ordinary customer can write — and `toee_hermes/plugin/hooks.py::_fence_safe`
neuters them at render on every layer, which is what covers values already in the store.

**L4's write scan is the injection leg only, deliberately (0.0.5 S08, D2).** `scan_memory_write`
runs `scan_injection` over the slot value and its `evidence` and hard-rejects — the write fails,
nothing is scrubbed and stored. It does **not** run `scan_pii`: NFR-6's no-PII rule governs the
*shared* layers, and L4 is the layer a customer's own callback number belongs in, so a PII leg
here would reject correct data (`leave at back door, call 604-555-1212`). The rejection is
counted as `metric_event.metric = 'memory_pollution_rejected'` (S22's pollution numerator).

---

## Outside the layer model, and why

Four surfaces live in the same Postgres and are **not** memory layers. The rule that decides
it is the same one `LAYER_OF_ACTION` applies: a layer holds content the system reads back into
a turn on behalf of a customer.

| Surface | What it is | Why not a layer |
| --- | --- | --- |
| Workbench Accounts | staff identity + roles | operator identity, not customer memory |
| Knowledge publish state | the 6 governed operational-policy slots + history | authored content; the L5 boundary row pins it as explicitly NOT the corpus |
| **Quality feedback** (ADR-0154: `interaction_review`, `draft_feedback`) | judgments **about** the system's output — reviews, thumbs, draft outcomes | never read back into a turn; it measures the system, it is not something the system remembers about a customer |
| **Review items** (0.0.5 S15: `review_item`) | pending **decisions about** memory — graduation, blast-radius, persona-review and retirement candidates raised by S10/S20/S25 | a queue entry, not an entry: it references memory by `subject_ref` and carries the emitter's evidence, and no turn ever reads it back. Deciding one changes only that row's status |

**One known limitation, recorded here rather than discovered later.** S15's
`reclassify_proposal` is the first catalog action that writes **two** layers: it rejects an L6
proposal and proposes an L7 entry in one governed action. `LAYER_OF_ACTION` maps one action to
one layer, so it declares `L7` — the layer whose content is *created*, which is why an admin
re-classifies at all. The L6 half is not lost from the governance record: it runs through
`reject_experience` (declared L6 in its own right) and lands its own audit row, plus a
`review_item_reclassified` row linking the two ids. If a second two-layer action ever appears,
the map's value type is what should change.

The quality-feedback row is stated rather than left to inference (0.0.5 S06, NFR-8). It arrived
with the merged 0.0.4 work and had **no row here at all**, so its four `toee_feedback` actions
were declared non-memory-writes by *absence* — and a reader would plausibly have expected them
under L3 next to "eval records". They are not: L3 Operational is Follow-up Case / Workbench
Audit Log / auto-handled evidence / eval records, and these two tables are none of those.
`toee_hermes/memory_layers.py` declares all four `None`, which agrees with this row.

Feedback *derived* into a proposal is a different thing and does become memory: that is the
`feedback_derived` provenance value on L6/L7 proposals, which enters through the same governed
propose→confirm gate as any other proposal.

---

## Change log

- **2026-07-28 (0.0.5 S11)** — L4 gained the **whole-binding erase** and its deletion-success
  tripwire (FR-13/FR-14, US7): a governed loop over the existing per-slot clear, reaching the
  verified binding *and* every linked channel's provisional binding (D10 — an erase that
  stopped at the verified key would be undone by the cross-channel merge on the customer's
  next turn). See the L4 section above for which stores it touches and which it deliberately
  does not. This is a *forgetting* mechanism, and the **forgetting table** that will hold it
  next to retention and L6/L7 retirement is still S22's — this entry does not pretend to be it.

- **2026-07-28 (0.0.5 S06)** — L7 shipped: the `<confirmed_lexicon>` glossary at both turn
  seams behind two independent default-OFF flags, `default_rule` conditions evaluated at
  render with a confirm-first phrasing, and the **L4-over-L7 precedence** rule (order +
  wording, both tripwire-tested) —
  [ADR-0161](../adr/0161-l7-semantic-lexicon-governed-domain-language-and-its-two-seams.md).
  L7 status: 🔬 exploring → ✅ shipped. This entry also lands three things the map was
  missing: the **L1–L7 routing decision tree**, the **three L7 boundary rows**, and an
  explicit **outside-the-layer-model** section that finally places the ADR-0154
  quality-feedback stores (previously placed nowhere, so their actions were declared
  non-memory-writes by absence rather than by decision). Also records the D19 fence-escape
  fix on the render side. The **forgetting table** is still outstanding — it lands with S22.

- **2026-07-27 (0.0.5 S12)** — the boundary section gained a machine-checked half:
  `LAYER_OF_ACTION` (a declaration per catalog action) plus the tripwire suite that keeps it
  complete, asserts injection-fence composition, and tests the matrix rows it honestly can.
  Declarative + tests only; no runtime behavior changed, no layer decision revised.

- **2026-07-21 (0.0.5 exploration)** — L7 Semantic lexicon opened (🔬 exploring): admin-governed,
  conversation-fed domain language (aliases / normalizers / contextual defaults) applied
  deterministically at the tool boundary + as a bounded glossary; the L1–L7 scope map, routing
  decision tree, and anti-gap/anti-overlap mechanisms are recorded in
  [`workspace/0.0.5/EXPLORATION.md`](../../workspace/0.0.5/EXPLORATION.md). ADRs deferred to the
  0.0.5 slices per the maintenance rule (docs follow decisions, not intentions).

- **2026-07-21 (S25)** — L6 shipped: confirmed-entry injection (copilot draft turn
  + external read-only), two independent injection flags (both default OFF), the
  eval-determinism pin, and the folded-in draft-turn-inert regression —
  [ADR-0152](../adr/0152-l6-agent-experience-confirmed-injection-and-eval-pin.md).
  Real-traffic cap/ranking calibration deferred post-launch (FR-27). L6 status:
  🔬 exploring → ✅ shipped.
- **2026-07-20 (S19)** — L4 cross-channel provisional merge shipped: a verified
  turn now merges provisional slots from every linked channel identity, not
  just its own, per a documented precedence — ADR-0151 (supersedes ADR-0112's
  v1 cross-channel non-goal).
- **2026-07-20 (S13)** — L4 S20 reversal: the copilot draft turn's `toee_customer_memory`
  write overlay is removed (propose-only); reads and Knowledge are unaffected —
  ADR-0150.
- **2026-07-20 (S12)** — L5 shipped: formal decision record + isolation/deadline rationale +
  FR-2 open question in [ADR-0149](../adr/0149-hybrid-lexical-embedding-knowledge-retriever.md);
  productionized FR-7/FR-7b gates harness re-measures the shipped hybrid rung (p95 48.4ms @167
  chunks, recall@3 73% synthetic-interim) — corrects audit finding 1 (the spike's S-LAT only ever
  measured the rejected FTS-only rung).
- **2026-07-20** — L5 decided (Path Y-embed hybrid, gbrain rejected) on spike evidence; L6 opened
  (agent-experience memory) after researching Hermes's own memory subsystem; this map created.
- **2026-07-16** — 0.0.2 shipped L4 write attribution (`copilot_agent` source + `actor_account_id`,
  carve-out removed) — ADR-0148.
- **earlier** — 0.0.1 shipped L4 Customer Memory; ADR-0140 moved the substrate to Postgres.
