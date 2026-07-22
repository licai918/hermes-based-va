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

## Candidate slots 2+ — deliberately empty

0.0.4 (job queue, worker cutover, scoring mechanism, TS cleanup) is heavy and in flight.
Further 0.0.5 candidates land here only after 0.0.4 ships or an owner decision reprioritizes.
