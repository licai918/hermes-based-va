# 0.0.2 — Exploration (NOT a PRD)

- **Status:** exploration only. Nothing here is committed scope. This is a
  possibility space for the next iteration; each candidate lists open questions
  to resolve before any of it becomes a PRD.
- **Builds on:** 0.0.1 (Customer Memory activation — [PRD](../0.0.1/PRD.md),
  branch `feat/0.0.1-customer-memory` / PR #54).
- **Date opened:** 2026-07-14

---

## How to read this

Each candidate is sized (S/M/L, rough) and carries **options with trade-offs**,
not a decision. The write-decision guardrail (Candidate 1) is the one the product
owner explicitly asked to capture; the rest are things 0.0.1 surfaced or deferred.
When one candidate is chosen for 0.0.2, it graduates into `workspace/0.0.2/PRD.md`
via the normal brainstorm → PRD → slices flow.

---

## Candidate 1 — Write-decision guardrail for Copilot memory writes (explicit ask)

**Why.** 0.0.1 / S20 connected gap #2: the Copilot **AI drafting agent** can now
**autonomously persist** `toee_customer_memory.upsert_preference` writes (they
reach Postgres under the correct customer key). The guardrails that exist are
**integrity-only**:

- `source` is framework-derived from the profile (model can't forge `customer_explicit`);
- the binding key is derived from `context.identity` (can't target another customer);
- fail-closed `policy_blocked` when no identity resolves;
- the slot is constrained to the fixed four-slot enum.

**The gap:** there is **no authorization gate on _whether/when_ the model writes**,
and no prompt instruction constraining it. A draft-turn write is tagged
`employee_confirmed` even though no explicit confirmation happens at write time
(defensible — Copilot is employee-operated and the rep reviews the draft — but
the label overstates the control). ADR-0111's intent is "writes happen after
employee confirmation."

**Options (not decided):**

| # | Approach | Enforcement | Cost | Notes |
| --- | --- | --- | --- | --- |
| **A** | **Prompt-level guard** — instruct the Copilot draft persona to write a preference only when the customer/employee explicitly stated a durable preference in-context; never from inference. | Soft (LLM behavior) | S | Cheapest; back it with an eval (option E). Mirrors the external persona's existing "no inferred write" rule. |
| **B** | **Distinct `source` value** — add e.g. `copilot_agent_inferred` (vs `employee_confirmed`) so an AI-draft write is *auditable as such* and downstream can review/filter it. | Honest audit, not prevention | S–M | Enum + handler + migration-free (column already `text`). Makes the audit truthful; pairs well with A. |
| **C** | **Read-only memory on the draft turn** — restrict the Copilot *draft* boot's tool surface so the LLM can only *read* memory; *writes* go only through the deterministic UI button (dispatch route). | Hard (allowlist) | M | Cleanest governance, BUT it partially reverses the just-made gap-#2 decision (draft agent can't write at all). Needs per-path allowlisting (draft boot uses a memory-read-only variant), which the profile allowlist doesn't express today. |
| **D** | **Propose → confirm loop** — the draft agent *proposes* a preference change surfaced to the rep, who confirms before it persists. | Hard (human in loop) | L | Most faithful to ADR-0111 "after employee confirmation." Real feature: a proposal surface in the Workbench + a confirm action. |
| **E** | **Copilot no-inferred-write eval** — a scenario (mirror external scenario 26) asserting the draft agent does not persist a preference from tone/inference. | Regression guard for A | S | Not a guard by itself; locks A's behavior. |

**Leaning (for discussion, not decided):** A + B + E as the lightweight combo
(soft prompt guard + honest audit label + eval), with D as the "correct" heavier
version if autonomous writes prove too loose in UAT. C only if the product owner
decides the UI button should be the *sole* write path after all.

**Open questions:**
- Does the Copilot draft agent actually *need* to write preferences, or is the
  deterministic UI button sufficient in practice? (If the latter, lean C.)
- Is `employee_confirmed` an acceptable label for an AI-draft write, or does the
  audit need to distinguish them (option B)?
- Related: the S02 `channel_identity_id` param carve-out now "has teeth" (see
  Candidate 4) — resolve alongside this.

---

## Candidate 2 — gbrain knowledge layer (the original "M2")

**Why.** The knowledge the agent uses for company/brand/product is hollow (persona
+ 6 policy slots; `search_public_site` is a 2-entry mock; the ADR-0001/0002/0031
RAG/crawl was never built). gbrain (github.com/garrytan/gbrain) is the candidate
backend for a real, retrievable knowledge layer. Already explored in the 0.0.1
[design spec](../../docs/superpowers/specs/2026-07-10-memory-architecture-activation-design.md)
(§M2) and [PRD §4.2](../0.0.1/PRD.md) (FR-8…FR-10, PAC-8).

**Must clear three spikes before any commitment (hard gates):**
1. **Latency** — non-synthesis retrieval < 800 ms for an in-turn SMS tool call;
   synthesis mode is out of scope in-turn regardless.
2. **Server API shape** — a server-side-callable retrieval endpoint (plain HTTP
   preferred; else a minimal read-scoped MCP-HTTP client).
3. **Deployment isolation** — gbrain's Postgres+pgvector in a **separate database**
   from the business datastore (knowledge store carries **no PII**).

**Shape (from the 0.0.1 design):** `search_public_site` backed by a
`GbrainKnowledgeDriver` behind the unchanged governed `toee_knowledge_search`;
`brain/` markdown authored in-repo, PR = publish gate, `brain/` never holds live
facts / policy-slot copy / PII; gbrain's write/admin tools never exposed to the
customer agent; degrade to `found=false`. Boundary lint rejects content that
restates a policy slot or a live fact.

**Open questions:**
- Same-repo `brain/` vs a separate content repo (0.0.1 leaned same-repo subdir).
- Who authors + reviews knowledge content (KnowledgeOps overlap with the existing
  policy-slot flow)?
- Is gbrain the right dependency, or is a smaller in-house retriever over `brain/`
  markdown enough for v1? (gbrain has 700+ open issues; evaluate maturity.)

**Size:** L (spikes + driver + authoring flow + terminology/ADR updates).

---

## Candidate 3 — Customer Memory retention sweep (RK-9)

**Why.** 0.0.1 explicitly deferred the retention job. Provisional slots accumulate
(every unmatched caller who states a preference creates a row that may never merge
or expire); verified slots also have no sweep. ADR-0004/0116 define the retention
policy; the columns (`created_at`, `last_interaction_at`) already exist.

**Shape:** a scheduled sweep (cloud slice or a local cron) that deletes/ages
`customer_memory_slot` rows past retention, honoring the ADR-0004 classes.
**Open questions:** retention windows per slot kind? provisional vs verified
different TTLs? where the job runs (ties into the deferred Cloud Tasks/Cloud SQL
slice). **Size:** M.

---

## Candidate 4 — Harden the `channel_identity_id` carve-out (now has teeth)

**Why.** S02 left an `internal_copilot`-only fallback: when `context.identity`
yields nothing, `resolve_customer_memory_binding` honors a **model/param-supplied**
`channel_identity_id` → `provisional:{channel_identity_id}`. Pre-0.0.1 this only
ever hit mock; **post-S20 a model that emits that param during a draft can direct
a persisted write to a provisional key it names.** The draft path binds from
context first (so it's not the common case), but the carve-out is now live.

**Options:** (a) remove the param carve-out entirely (context-only binding
everywhere; the UI dispatch route already passes `case_id`, not this param);
(b) restrict it to a non-model actor (only the deterministic BFF may set it);
(c) leave it but add an eval that the draft agent never uses it. **Lean (a)** —
it was a stopgap and the case-identity path (S16) supersedes it. **Size:** S.
Resolve with Candidate 1.

---

## Candidate 5 — Small cleanups carried forward from 0.0.1

Low-risk hygiene the 0.0.1 reviews flagged and parked (each S–XS):

- **De-dup `_customer_memory_extra_drivers`** — verbatim in both `openrouter.py`
  and `copilot_turn.py`; natural home is `tool_backend.py` (already exports
  `memory_enabled` + `select_tool_driver`). Kills drift on a security-adjacent gate.
- **Copilot `_load_case_memory` identity-lookup swallow** — the `load_case_identity`
  branch still swallows silently (S11 only logged the `load_customer_memory`
  branch); add the same PII-safe warning.
- **Rename the S15 characterization test** — `test_dispatch_route_correction_persists_but_misses_a_verified_customers_read_key` now documents the *legacy* `channel_identity_id`
  carve-out, not an open bug; the name reads like a defect. Rename/reframe (ties to Candidate 4).
- **Workbench preferences panel visual polish** — S18's panel is an un-renormalized
  `flex` insert; wants a real-browser layout pass (also on the UAT list).
- **Shared slot constant on the TS side** — `PREFERENCE_SLOTS` is a hand-written
  literal in `apps/workbench` because `MEMORY_PREFERENCE_SLOTS` isn't exported from
  `@toee/domain-adapters`; export + import so a 5th slot can't silently drift.

---

## Candidate 6 — Connection pooling (RK-7), if scale demands

**Why.** 0.0.1 opens ~2–3 Postgres connections per turn (merge store + read store +
write driver), no pool (ADR-0142 deferred pooling to the cloud slice). Fine at SMS
volume; a scaling cliff later. **Only pursue if load testing shows it matters.**
**Size:** M (ties into the deferred Cloud SQL/Cloud Run slice).

---

## Cross-cutting open questions

- **0.0.2 theme:** is 0.0.2 the *knowledge layer* (Candidate 2, big), or a
  *governance + hardening* pass (Candidates 1/3/4/5, smaller), or both? Picking one
  theme keeps the iteration focused.
- **Sequencing vs 0.0.1 merge:** most of these assume 0.0.1 (PR #54) has merged.
  Candidate 1/4 touch the same memory code 0.0.1 just wrote — do them right after
  merge to avoid churn.

## Explicitly parked (not 0.0.2 unless promoted)

- Cross-channel provisional merge (ADR-0112 v1 non-goal).
- External memory providers (mem0/honcho — rejected in 0.0.1).
- Any change to how live facts are served (stay real-time Shopify/QBO reads).
