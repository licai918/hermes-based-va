# 0.0.2 — Exploration → sharpened scope (NOT yet a PRD)

- **Status:** exploration, **grilled and trimmed to committed scope** (2026-07-14).
  This is the PRD-ready shape for the "govern + harden" iteration. The unselected
  candidates were moved to [0.0.3 exploration](../0.0.3/EXPLORATION.md).
  **Next:** brainstorm → `workspace/0.0.2/PRD.md` → slices.
- **Builds on:** 0.0.1 (Customer Memory activation — [PRD](../0.0.1/PRD.md),
  merged PR #54). Branch `feat/0.0.2-memory-governance` (rebased on the merge).
- **Date opened:** 2026-07-14

---

## Scope (committed)

1. **Write-decision guardrail** for Copilot memory writes — *governance* (S–M) — **A + B + E + NFR-3**
2. **Remove the `channel_identity_id` carve-out** — *security* (S)
3. **Carried-forward cleanups** — *hygiene* (S)

The knowledge layer, write-guardrail **option D**, retention sweep, pooling,
cross-channel, transparency, and instrumentation were **moved to 0.0.3**.

---

## ✅ Route decision (2026-07-14)

Product owner (licai) selected the **"Govern + harden the shipped memory"** theme,
right after the 0.0.1 PAC sign-off and PR #54 merge. Rationale: touches the exact
memory code 0.0.1 just wrote (do it now to avoid churn), closes the S20
autonomous-write authorization gap (the thing that makes the feature *trustworthy*),
and discharges the PAC-2 eval-coverage debt recorded in the sign-off. The knowledge
layer is kept as its own **0.0.3** so it gets a full spike → PRD cycle. One ADR
covers the clustered governance surface.

---

## 🔬 Grill outcomes (2026-07-14) — grounded in ADRs/code, decided by product owner

**Decisions**

1. **Source discriminator (Candidate 1B):** distinguish an AI-draft write from a
   UI correction by **`context.user_id` presence** — the UI dispatch route sets
   `actor_account_id → context.user_id` (`tool_dispatch_app.py:190-204`); the
   draft turn boots unbound with no actor. So `resolve_memory_write_source`
   (today `mock/memory.py:233-259`, maps INTERNAL→`employee_confirmed` on profile
   alone) gains: INTERNAL **with** `user_id` → `employee_confirmed`; INTERNAL
   **without** → new `copilot_agent`.
2. **Actor column (NFR-3):** add a **nullable** actor column to
   `customer_memory_slot` (schema `0001_initial_schema.sql:77-88` — no actor
   column today). UI correction → the rep's `account_id`; **agent write and merge
   write → NULL** (no human operator). Nullable ALTER, no backfill.
3. **Carve-out removal (Candidate 4):** remove it; **delete** the S15
   characterization test (its behavior ceases to exist); **update** the other
   three carve-out tests to assert the new `policy_blocked` contract.
4. **Eval semantic judgment (Candidate 1E / Candidate 5):** use an **LLM-judge**
   for the semantic legs (honored, no-unprompted-recall), with guardrails:
   **advisory only, NOT a CI merge gate** (a non-deterministic judge would flake
   the gate — the deterministic legs `forbid_inferred_upsert` + `must_not_contain`
   stay the hard gate); **injection-hardened** judge prompt (the reply + injected
   untrusted memory are fenced DATA, never instructions to the judge); a **cheap
   model** (e.g. haiku); and **`no-inferred` stays mechanical** (`did_upsert`) —
   the judge covers only the two semantic checks.

**Corrections the code forced (stale exploration bullets, now dropped)**

- Candidate 5 "dedup `_customer_memory_extra_drivers`" is **already done**
  (`tool_backend.py:82`, commit d5b8009).
- Candidate 5 "workbench visual polish" is **discharged** (the `<h2>` fix +
  desktop layout review this session).
- Candidate 5 "rename the S15 characterization test" → superseded: with the
  carve-out removed (Candidate 4), the test is **deleted**, not renamed.

---

## Candidate 1 — Write-decision guardrail (A + B + E + NFR-3) — *governance* (S–M)

### Why
0.0.1 / S20 connected gap #2: the Copilot **AI drafting agent** can now
**autonomously persist** `toee_customer_memory.upsert_preference` writes (they
reach Postgres under the correct customer key). The guardrails today are
**integrity-only** (source framework-derived, binding-key from `context.identity`,
fail-closed when no identity, fixed four-slot enum). **The gap:** no authorization
gate on *whether/when* the model writes, and no prompt instruction constraining it
— a draft-turn write is tagged `employee_confirmed` even though no explicit
confirmation happens at write time. ADR-0111 (:30, :35) says writes happen "after
employee confirmation" and forbids "autonomous preference writes without … employee
confirmation."

### The four pieces (sharpened)
- **A — prompt guard.** The Copilot draft persona (`copilot_turn.py:81-108`,
  `_SYSTEM_MESSAGES`, 4 channels: sms/email/internal_note/chat) says **nothing**
  about memory writes today. Mirror the external persona's exact rule
  (`persona.py:99-103`: *"ONLY when the customer explicitly asks you to remember a
  preference … NEVER save a preference you merely inferred"*), adapted to
  *"…explicitly stated in **this case's** conversation."* The draft agent **keeps**
  `upsert_preference` (guarded, not removed) — consistent with the A+B+E choice.
- **B — `copilot_agent` source value.** Add `copilot_agent` to
  `MEMORY_SOURCE_VALUES` (`mock/memory.py:40-44`, currently the three:
  `customer_explicit`, `employee_confirmed`, `merged_provisional`). Discriminate
  by `user_id` presence (decision 1). The `customer_memory_slot.source` column is
  already `text` (no migration). Makes the §6.4 audit trail honest — a supervisor
  can tell an AI-inferred write from a rep's deliberate correction.
- **E — copilot no-inferred eval + the honored judge.** A new
  `30-copilot-memory-no-inferred-write` scenario on the **copilot draft-turn**
  path, mirroring external scenario 26's `forbid_inferred_upsert` +
  `tool.forbidden_tools` (both stay mechanical). Plus the LLM-judge (decision 4)
  for the semantic "honored" leg (which also fixes the Candidate 5 freebie).
  **Risk to verify (spike):** the eval runner's scenario 26 is `channel: textline`;
  confirm it can drive an `internal_copilot` draft turn, or E needs harness
  plumbing (bumps E from S to M).
- **NFR-3 — actor column.** Persist the acting rep (decision 2). The dispatch
  route resolves `actor_account_id → context.user_id` (`tool_dispatch_app.py:190-204`)
  but `_upsert_preference` (`datastore/handlers/memory.py:50-82`, inserts 7 columns)
  drops it — add the nullable column + thread `context.user_id`.

### Audit / acceptance
- Every persisted write carries `source` distinguishing UI-confirmed
  (`employee_confirmed`) vs agent-inferred (`copilot_agent`) vs merge
  (`merged_provisional`); UI writes also carry the rep's actor, agent/merge writes NULL.
- Eval: scenario 30 green (mechanical no-inferred on the copilot path); the
  LLM-judge honored/silent signal recorded as an advisory (non-gating) leg.

### Deferred within Candidate 1
Option **D (propose → confirm)** — the governance-faithful north star where the
draft agent only *proposes* and a rep *Accepts* in the panel — **moved to
[0.0.3 exploration](../0.0.3/EXPLORATION.md)**. Promote if UAT of the A+B+E
autonomous path feels loose.

**Size:** A+B+E+NFR-3 = S–M.

---

## Candidate 4 — Remove the `channel_identity_id` carve-out — *security* (S)

### Why
S02 left an `internal_copilot`-only fallback: when `context.identity` yields
nothing, `resolve_customer_memory_binding` (`mock/memory.py:215-224`) honors a
**model/param-supplied** `channel_identity_id` → `provisional:{channel_identity_id}`.
Post-S20 a model emitting that param during a draft can direct a persisted write to
a provisional key it names. S16's `_resolve_case_identity`
(`tool_dispatch_app.py:84-124`, binds from `case_id`) superseded it — the carve-out
is now only reached when case-identity resolution returns `None`.

### The change (decided)
- **Remove** the fallback block (`mock/memory.py:215-224`) → context-only binding;
  an unresolvable case fails closed to `policy_blocked` (correct — no write on an
  unidentifiable case).
- **Delete** the S15 characterization test (`test_datastore_driver_memory.py:194`,
  `test_dispatch_route_correction_persists_but_misses_a_verified_customers_read_key`)
  — it directly asserts the carve-out's now-removed dead-key output.
- **Update** the three tests that assert the carve-out succeeds
  (`test_customer_memory_binding.py:115`, `test_memory.py:407`,
  `test_datastore_driver_memory.py:180`) to assert the new `policy_blocked` contract.
- The external-ignores-param tests (`test_customer_memory_binding.py:103`,
  `test_memory.py:328`) are **unaffected** (external already fails closed). No eval
  `.yaml` depends on the carve-out.

**Size:** S.

---

## Candidate 5 — Carried-forward cleanups (trimmed) — *hygiene* (S)

Surviving items after the grill (dedup + visual-polish dropped as done; the
S15-test item moved to Candidate 4):

- **Fix the eval `honor_injected_preference` freebie** — `turn_result.py:72-74`
  forces `honored_injected_preference=True` whenever a `memory_preset` exists, and
  `assertions.py:198-209` then always passes. Replace the honored leg with the
  **LLM-judge** (decision 4) so it is genuine (advisory, non-gating). **Add the
  `no-unprompted-recall` scenario** (external channel: memory preset present,
  customer says nothing memory-related, judge asserts the agent stays silent about
  the stored preference) — discharges the **PAC-2** eval-coverage gap recorded in
  the 0.0.1 UAT sign-off.
- **`_load_case_memory` identity-lookup swallow** — the `load_case_identity` branch
  (`copilot_turn.py`) still swallows silently (S11 logged only the other branch);
  add the PII-safe warning.
- **Export the slot constant on the TS side** — `PREFERENCE_SLOTS` is a
  hand-written literal (`apps/workbench/lib/gateway/types.ts:120`) and
  `MEMORY_PREFERENCE_SLOTS` is a module-local **unexported** const
  (`packages/domain-adapters/src/mock/memory.ts:28`). Export it + import in
  workbench so a 5th slot can't silently drift. (The Python copy at
  `hermes/toee_hermes/drivers/mock/memory.py:27` stays a documented parallel —
  cross-language share is out of scope.)

**Size:** S.

---

## Cross-cutting (0.0.2)

- **Governance cluster → one ADR.** Candidates 1 + 4 both touch the write/binding
  governance surface; a single ADR update covers the new `copilot_agent` source
  value, the actor column, and the carve-out removal (amends ADR-0111 / 0112 / 0114).
- **Sequencing.** Done now, right after PR #54, on `feat/0.0.2-memory-governance`
  (rebased on the merge), to avoid churn/conflicts with the just-shipped code.

## Explicitly parked (not 0.0.2)

- Everything **moved to [0.0.3 exploration](../0.0.3/EXPLORATION.md)**: knowledge
  layer, write-guardrail option D, retention sweep, connection pooling,
  cross-channel continuity, transparency & control, effectiveness instrumentation.
- External memory providers (mem0 / honcho — rejected in 0.0.1).
- Any change to how live facts are served (stay real-time Shopify/QBO reads).
