# Memory architecture — layer map

**What this is.** The **current-state structural view** of the Hermes VA's memory: what each
layer holds, where it physically lives, how it is retrieved, how it is governed, and which ADRs
decide it.

**What this is NOT.** Not a glossary — that is [`CONTEXT.md`](../../CONTEXT.md). Not a decision
record — those are [`docs/adr/`](../adr/). This file **links** rather than restates, deliberately,
so it cannot drift out of sync with them.

> **Maintenance rule.** When an ADR lands that changes a layer, update that layer's row **in the
> same PR**. No separate doc-maintenance ritual — the ADR is the trigger.

*Last updated: 2026-07-20 (0.0.3 S12 — L5 knowledge ADR + gates harness).*

---

## At a glance

| # | Layer | Holds | Physically | Retrieval | Status |
| --- | --- | --- | --- | --- | --- |
| **L1** | Identity Graph | channel identities, identity snapshots, Shopify/cross-system links, consent (SMS Opt-Out), match history | `toee_va` Postgres | exact key (phone / email → identity) | ✅ shipped |
| **L2** | Conversation | Customer Thread, Email Thread, SMS Session windows, MessageTurn, AgentTurnContext | `toee_va` Postgres | keyed by thread / session id | ✅ shipped |
| **L3** | Operational | Follow-up Case, Workbench Audit Log, auto-handled evidence, eval records | `toee_va` Postgres | keyed / queried per workflow | ✅ shipped |
| **L4** | Customer Memory | 4 governed preference slots per customer | `toee_va` Postgres | **exact** `WHERE binding_key = ?`, injected per turn | ✅ shipped (0.0.1 + 0.0.2) |
| **L5** | **Knowledge** | shared, non-PII company/product corpus | **separate `toee_knowledge` DB** | **hybrid lexical FTS + dense embedding**, top-k chunks | ✅ **shipped** ([ADR-0149](../adr/0149-hybrid-lexical-embedding-knowledge-retriever.md)) |
| **L6** | **Agent experience** | what the agent learns from doing the job | TBD | TBD | 🔬 **exploring** |

L1–L4 are the **four-layer model** of [ADR-0110](../adr/0110-native-memory-four-layer-model.md).
L5 and L6 are additions in flight — see below.

The same Postgres also holds **Workbench Accounts** and **knowledge publish state** (the 6
governed operational-policy slots + history). Those sit **outside** the four-layer model; they are
authored content, not memory.

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

## L6 — Agent-experience memory *(exploring)*

*What the agent learns from doing the job* — distinct from customer PII (L4), authored corpus
(L5), and behaviour contract (`persona.py`). Candidate 8 of
[the 0.0.3 exploration](../../workspace/0.0.3/EXPLORATION.md).

**Scope check:** ADR-0111/0140 rejected Hermes built-in memory **as the store for customer
business records**. They say nothing about the agent accumulating its own operational
experience — L6 is that gap, a new layer, not a re-litigation.

**Direction under exploration:** copy Hermes's *learning loop* (the background self-improvement
review fork), not its *store* — routing proposed learnings through our governed
tool → Postgres → audit, gated **propose → confirm**, starting on the internal copilot where reps
already review every draft.

**Live risks** carried in the candidate: model-authored PII, unbounded transcript retention,
**cross-profile recall crossing the EXTERNAL/INTERNAL/SUPERVISOR security boundary**,
poisoned-memory blast radius, and eval determinism.

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
| Any layer | model-supplied write attribution | `source` + `actor_account_id` are framework-derived |

---

## Change log

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
