# PRD — Memory Governance & Hardening

- **Version:** 0.0.2
- **Date:** 2026-07-14
- **Status:** Draft for review
- **Owner:** licai
- **Exploration + grill record:** [workspace/0.0.2/EXPLORATION.md](EXPLORATION.md)
  (candidates, the four locked "Grill outcomes", grounded touchpoints)
- **Builds on:** 0.0.1 Customer Memory activation — [PRD](../0.0.1/PRD.md), merged PR #54, PAC-1…7 signed off.
- **Related ADRs:** 0111 (write sources — **amended here**), 0112 (provisional merge), 0114 (v1 actions/allowlists — **amended here**), 0140 (datastore = system of record), 0142 (per-profile dispatch topology). This iteration ships **one new ADR** covering the `copilot_agent` source value, the actor column, and the carve-out removal.

---

## 1. Background & problem

0.0.1 shipped Customer Memory (L4) across the external and Copilot surfaces and was
signed off (PAC-1…7). In closing the last PAC-4 gap, **S20 connected the Copilot AI
drafting agent's autonomous write path**: a draft turn can now **persist**
`toee_customer_memory.upsert_preference` to Postgres under the correct customer key.
That was the right plumbing, but it exposed a governance gap the milestone
knowingly deferred:

1. **No authorization gate on the model's write.** The guardrails today are
   **integrity-only** — `source` is framework-derived, the binding key comes from
   context, an unresolvable identity fails closed, and only the four v1 slots are
   writable. But nothing constrains **whether or when** the model writes, and the
   draft persona says nothing about write-discipline. An AI-draft write is tagged
   `employee_confirmed` even though **no employee confirmed it** at write time —
   contradicting ADR-0111's "writes happen after employee confirmation."
2. **A model-nameable binding key still exists.** The S02 `internal_copilot`
   `channel_identity_id` param carve-out lets a model that emits that param during
   a draft direct a persisted write to a `provisional:{…}` key it names. S16's
   case-identity resolution superseded it as the primary path, but the carve-out
   is still live.
3. **The eval "honored" leg is a freebie.** The eval harness marks
   `honored_injected_preference = True` whenever a scenario has any memory preset,
   so the "did the agent honor the preference" assertion always passes — it proves
   nothing. Relatedly, **PAC-2 ("no over-recall") has no eval leg at all** (flagged
   in the 0.0.1 sign-off), and the four preference slots are hand-copied across
   three files.

**Consequence today:** an AI-drafted preference write is indistinguishable in the
audit from a rep's deliberate correction; a draft model that emits
`channel_identity_id` can name a binding key; and the eval suite would stay green
even if the agent ignored every stored preference.

## 2. Goals

- **G1 — Honest, authorized writes.** An AI-draft memory write is
  prompt-discouraged from inference, **distinguishable in the audit** from a rep's
  confirmed correction, and **attributable to the acting rep** when one exists.
- **G2 — Context-only binding.** Remove the last path by which a model-supplied
  parameter can direct a memory write's binding key.
- **G3 — Genuine eval coverage.** The "honored" and "no-unprompted-recall"
  behaviours are actually inspected (not freebie-passed), closing the PAC-2 gap.
- **G4 — Governance hygiene.** Carried-forward cleanups that reduce drift on the
  security-adjacent write/binding surface.

### Non-goals

- **No propose→confirm (option D).** The draft agent keeps its (now guarded)
  write; D — where the agent only *proposes* and a rep *Accepts* — is the 0.0.3
  north star, promoted only if UAT of the guarded autonomous path feels loose.
- **No knowledge layer** (gbrain / retriever) — that is 0.0.3.
- **No retention job, connection pooling, cross-channel continuity, or memory
  transparency surface** — all 0.0.3.
- **No change to shipped 0.0.1 mechanics** — read injection, provisional→verified
  merge, fail-closed binding, and no-DB degradation are unchanged.
- **The LLM-judge is advisory, not a CI merge gate.**

## 3. Users

| Persona | Relationship to this iteration |
| --- | --- |
| **Customer Service Rep / Supervisor / Admin (Copilot)** | Makes deliberate UI corrections → `employee_confirmed`, **now with the acting rep recorded** |
| **Copilot AI draft agent** | May write a preference **only when the customer explicitly stated it in the case conversation**; its writes are now labelled `copilot_agent` (no human actor) |
| **Supervisor / auditor** | Can now **distinguish AI-inferred writes from rep-confirmed corrections** via `source` + actor |
| **Verified / provisional customer** | Read behaviour unchanged; a write on an **unresolvable** case now fails closed rather than binding a model-named key |

## 4. Requirements

> Each requirement's *Accept* line states the outcome; **§6 is the mechanism that
> proves it** — live (not mock), correctly labelled, and without regressing the
> shipped 0.0.1 behaviour.

### 4.1 Write-decision guardrail (Candidate 1)

- **FR-1 Draft-turn write discipline (prompt guard).** The Copilot draft persona
  instructs the agent to record a preference **only when the customer has
  explicitly stated a durable preference in this case's conversation** — never
  inferred from tone, history, or a single order — mirroring the external persona's
  existing rule. Soft (model behaviour), backed by FR-3's eval.
  - *Accept:* the Copilot draft persona carries the rule; the copilot-path
    no-inferred eval (FR-3) stays green.
- **FR-2 Honest source attribution (`copilot_agent`).** A write's `source`
  distinguishes a deliberate UI correction (`employee_confirmed`) from an AI
  draft-turn write (a new `copilot_agent` value), **derived by the framework from
  whether an acting employee is present** (`context.user_id` set by the dispatch
  route; absent on the unbound draft turn) — never model-supplied. Merge writes
  stay `merged_provisional`; external stays `customer_explicit`.
  - *Accept:* a UI-dispatched correction persists `source = employee_confirmed`; an
    AI draft-turn write persists `source = copilot_agent`; the model cannot forge
    either via tool params.
- **FR-3 Genuine no-inferred + honored eval on the Copilot path.** A new
  copilot-path no-inferred-write scenario (mirrors external scenario 26,
  **mechanical** via `did_upsert` / `forbidden_tools`) guards FR-1; the
  **honored** and **no-unprompted-recall** semantic legs are judged by an
  **LLM-judge — advisory (non-gating), injection-hardened, cheap model.**
  - *Accept:* the copilot no-inferred scenario is green on the **hard gate**; the
    LLM-judge honored/silent signal is recorded as an **advisory** (non-gating) leg.
- **FR-4 Actor attribution (NFR-3 closure).** Every memory write records the acting
  employee when one exists: a UI correction persists the rep's account id; an AI
  draft-turn or merge write persists **no** actor (null). Adds a nullable actor
  column to `customer_memory_slot` (no backfill).
  - *Accept:* a UI correction's row carries the rep's actor; an AI-draft write's
    row has a null actor; both are read back directly from Postgres.

### 4.2 Binding hardening (Candidate 4)

- **FR-5 Context-only binding (remove the carve-out).** Customer-memory binding
  derives **solely** from the ingress/case-resolved identity context; the
  `internal_copilot` `channel_identity_id` param fallback is **removed**. A write on
  a case whose identity cannot be resolved **fails closed (`policy_blocked`)**,
  never bound to a model-named provisional key.
  - *Accept:* a model supplying `channel_identity_id` cannot direct a write's
    binding key; an unresolvable-identity write is blocked, not param-bound; the UI
    dispatch route (`case_id` → identity) is unaffected.

### 4.3 Governance hygiene (Candidate 5)

- **FR-6 Eval honored-leg is real; PAC-2 gets coverage.** The eval "honored"
  assertion actually inspects the reply (LLM-judge, advisory) rather than passing
  unconditionally when a memory preset exists; a new **no-unprompted-recall**
  scenario asserts the agent stays silent about a stored preference the customer
  did not raise.
  - *Accept:* a transcript where the agent ignores or re-asks the preference no
    longer passes the honored leg; a no-unprompted-recall scenario exists and its
    (advisory) judge signal is recorded.
- **FR-7 Single source of truth for the slot list (TS side).** The four preference
  slots are exported once from `@toee/domain-adapters` and imported by the
  workbench, so a fifth slot cannot silently drift between copies. (The Python copy
  stays a documented parallel — cross-language sharing is out of scope.)
  - *Accept:* the workbench imports the slot constant rather than re-declaring it;
    adding a slot in the shared package propagates to the workbench.
- **FR-8 Observable identity-lookup failures.** The Copilot case-memory
  identity-lookup failure path logs a **PII-safe** warning (parity with the S11
  read-failure log), so a silently swallowed lookup is visible.
  - *Accept:* a forced identity-lookup failure emits the PII-safe warning
    (binding key + error type only, never PII); the turn still degrades cleanly.

### 4.4 Non-functional

- **NFR-1 Minimal migration risk.** The `copilot_agent` source value needs **no**
  migration (`source` is `text`); the actor column is a **nullable ALTER, no
  backfill, no read dependency** until FR-4 lands.
- **NFR-2 Audit truthfulness.** The trail distinguishes AI-inferred from
  rep-confirmed writes and records the acting rep — strengthening 0.0.1's NFR-3,
  which resolved the actor then dropped it.
- **NFR-3 Eval determinism preserved.** The CI merge gate stays deterministic — the
  LLM-judge is **advisory only**; the hard gates remain the mechanical assertions
  (`forbid_inferred_upsert`, `must_not_contain`).
- **NFR-4 No behaviour change to shipped 0.0.1 mechanics.** Read injection, merge,
  fail-closed binding, and degradation are unchanged; their suites stay green.

## 5. Scope for 0.0.2

**In:** §4.1 (FR-1…FR-4), §4.2 (FR-5), §4.3 (FR-6…FR-8), the full acceptance
mechanism of §6, and **one ADR amendment** covering the `copilot_agent` source
value, the actor column, and the carve-out removal (amends ADR-0111 / 0112 / 0114).

**Out (→ 0.0.3):** propose→confirm (option D), the knowledge layer, the retention
job, connection pooling, cross-channel continuity, memory transparency & control,
and effectiveness instrumentation — see [0.0.3 exploration](../0.0.3/EXPLORATION.md).

> Sizing: Candidates 1/4/5 are S–M each and touch the exact memory code 0.0.1 just
> wrote — done now, on `feat/0.0.2-memory-governance` (rebased on the merge), to
> avoid churn. See §7 (~4–7 days).

## 6. Acceptance & verification mechanism

0.0.1's lesson holds: acceptance is not "tests are green" — it is a mechanism that
proves the write-origin is **truthfully labelled and correctly bound**, and **fails
loudly** if the removed carve-out ever returns.

### 6.0 Proof principles (adapted from 0.0.1 §6.0)

1. **Live, not mock.** Every `source` / actor / binding assertion reads back
   **directly from Postgres**, not just a tool return value.
2. **Right label.** A write's `source` is asserted to **match its origin**
   (UI-correction vs draft-turn vs merge), not merely "a write happened".
3. **Deterministic gate.** The CI hard gate is mechanical; the LLM-judge is
   **advisory** (recorded, never gating), so the gate cannot flake.
4. **Removal tripwire.** A test proves the carve-out is **gone** — a model-supplied
   `channel_identity_id` no longer binds; it is `policy_blocked`. If that test ever
   shows a bound `provisional:{…}` key, the carve-out has silently returned — CI
   treats it as red. (This replaces the deleted S15 characterization test.)

### 6.1 Governance matrix (write-origin → label / actor / binding)

The single truth table 0.0.2 must make true, proven with real Postgres:

| Write origin | `source` | actor | binding |
| --- | --- | --- | --- |
| UI correction (dispatch route, `case_id`) | `employee_confirmed` | rep account id | case-resolved identity |
| AI draft-turn write | `copilot_agent` | null | case-resolved identity |
| provisional→verified merge | `merged_provisional` | null | verified key |
| unresolvable-identity write | — (blocked) | — | `policy_blocked` |
| model-supplied `channel_identity_id` | — (blocked) | — | `policy_blocked` (carve-out removed) |

### 6.2 Correctness rules (the logic judgments that must hold)

| # | Rule | Level | Assertion |
| --- | --- | --- | --- |
| **R1** | Source discriminator: INTERNAL + `user_id` → `employee_confirmed`; INTERNAL, no `user_id` → `copilot_agent`; EXTERNAL → `customer_explicit`; merge → `merged_provisional` | unit + datastore | `source` matches origin; model cannot forge |
| **R2** | Actor persistence: UI-correction row carries the rep actor; draft/merge row null | datastore | actor column matches origin |
| **R3** | Carve-out removed: a model-supplied `channel_identity_id` no longer binds → `policy_blocked` | unit + datastore + tripwire | blocked, never `provisional:{param}` |
| **R4** | Prompt-guard regression: the Copilot no-inferred scenario stays green (mechanical) | eval | draft agent does not persist an inferred preference |
| **R5** | Honored-leg genuine: a transcript where the preference is ignored/re-asked **fails** the honored judge (the freebie is gone) | eval-unit (judge on fixtures) | judge inspects the reply, not the preset |
| **R6** | No-unprompted-recall: the agent stays silent about a stored preference the customer did not raise | eval (advisory judge) | no unprompted recitation |

### 6.3 Test levels & seams (existing preferred; **confirm these**)

Almost every seam is an **existing 0.0.1 seam** — one new component, one spike:

- **Unit (pure):** `resolve_memory_write_source` discriminator (seam:
  `test_memory.py` / `test_customer_memory_write_source.py`);
  `resolve_customer_memory_binding` after carve-out removal (seam:
  `test_customer_memory_binding.py`).
- **Datastore integration (real Postgres, throwaway schema):** `source` + actor
  persisted per origin; carve-out removal → `policy_blocked`; the actor-column
  migration (seams: `test_datastore_driver_memory.py`,
  `test_customer_memory_datastore.py`).
- **Eval (behavioral replay):** the new Copilot no-inferred scenario (mechanical,
  **hard gate**); the honored-leg genuineness + no-unprompted-recall via the
  **LLM-judge** (advisory). **NEW seam:** the LLM-judge component — unit-tested with
  **fixture transcripts** (a small new seam, injection-hardening included).
- **Workbench (vitest):** `PREFERENCE_SLOTS` import from the shared package
  (existing vitest seam).
- **Removal tripwire:** a test asserting a model-supplied `channel_identity_id` is
  `policy_blocked` — the replacement for the deleted S15 characterization test.

> **Seams to confirm:** (a) all reuse existing 0.0.1 seams except **one new** — the
> LLM-judge, tested at the fixture-transcript level, the highest seam that still
> exercises it; (b) a **spike** gates FR-3: the eval runner's scenarios are
> `channel: textline` today — confirm it can drive an `internal_copilot` draft
> turn, or the Copilot no-inferred scenario needs harness plumbing (bumps FR-3 S→M).

### 6.4 Observability

Each persisted write now carries its origin **truthfully** in `source`
(`employee_confirmed` vs `copilot_agent` vs `merged_provisional`) plus the actor;
the per-turn structured log is unchanged (binding key + slot names, never values).
A supervisor/auditor reading a case's write history can tell an AI-inferred write
from a rep's deliberate correction — the audit's honesty is the headline
deliverable.

### 6.5 Product acceptance criteria (business-observable, product-owner sign-off)

Technical green (§6.0–6.4) proves the labels are truthful and the carve-out is
gone. **These prove the governance is felt.** Each is verified by evidence + a
manual UAT review, signed off by the product owner.

| ID | Product acceptance criterion | Verified by |
| --- | --- | --- |
| **PAC-1 Honest audit** | A supervisor can tell an AI-drafted preference write from a rep's deliberate correction (via `source` + actor). | datastore evidence + UAT (read a case's write history) |
| **PAC-2 No inferred writes on the Copilot path** | The AI draft agent does not persist a preference it merely inferred from the case. | eval (Copilot no-inferred) + UAT transcript |
| **PAC-3 No model-nameable keys** | A draft that emits a phone/param cannot direct where a write binds. | security test + UAT reasoning-trace review |
| **PAC-4 Genuine honored / silent signal** | The eval "honored" leg would go red if the agent ignored a preference; the agent stays silent about unraised preferences. | eval judge (advisory) + UAT |
| **PAC-5 No regression to shipped memory** | 0.0.1's PAC-1…7 still hold (read injection, merge, isolation, degradation). | 0.0.1 suites green + spot UAT |

### 6.6 Definition of Done — go/no-go gate for 0.0.2

Done only when **both** gates pass. Technical items require pasted command output;
product items require the product owner's written sign-off.

**Technical gate (engineering):**

- [ ] §6.2 R1–R6 green at their stated levels.
- [ ] §6.0.4 removal tripwire: a model-supplied `channel_identity_id` confirmed
      `policy_blocked` (the deleted S15 test's replacement).
- [ ] Real-path (live Postgres): `source` + actor persisted correctly per origin
      (the §6.1 matrix); carve-out removal.
- [ ] The Copilot no-inferred eval scenario green on the **hard gate**; the
      LLM-judge honored / no-unprompted-recall signals **recorded (advisory)**.
- [ ] The three updated carve-out tests assert `policy_blocked`; the S15
      characterization test **deleted**.
- [ ] 0.0.1 suites still green — **no regression** (NFR-4).
- [ ] The one ADR amendment merged (source value + actor column + carve-out removal).

**Product gate (product owner):**

- [ ] PAC-1…PAC-5 accepted on a UAT pass (read a case's write-origin history; a
      Copilot no-inferred transcript; a no-model-key check).
- [ ] Sign-off recorded (name + date) in this PRD or the 0.0.2 release note.

## 7. Milestones

| Milestone | Content | Est. |
| --- | --- | --- |
| **0.0.2 — memory governance** | Candidate 1 (prompt guard, `copilot_agent` source, actor column, Copilot eval + LLM-judge), Candidate 4 (carve-out removal), Candidate 5 (eval freebie fix + no-unprompted-recall, TS slot export, swallow warning), one ADR | **~4–7 days** |
| **0.0.3 — knowledge layer** | gbrain vs in-house retriever (spikes → driver → `brain/` authoring) + the deferred governance items | post-spike |

Smaller than 0.0.1 (no new surface, mostly existing seams). The two size risks are
the LLM-judge component and the eval-harness Copilot-channel spike (§6.3, RK-5).

## 8. Risk register

| ID | Risk | Sev | Disposition | Mitigation / where addressed |
| --- | --- | --- | --- | --- |
| **RK-1** | Prompt guard is soft — the "explicit statement" trigger is model behaviour (same class as 0.0.1 RK-1) | 🟠 | In-design | FR-1 mirrors the proven external rule; FR-3 eval regression; FR-2's `copilot_agent` label makes an inferred write **visible** even if one slips |
| **RK-2** | The `user_id` discriminator mislabels if a future non-UI internal path sets `user_id`, or a UI path forgets it | 🟠 | In-design | R1 unit test pins the mapping; document the invariant in the ADR; the actor column cross-checks (UI ⟺ actor present) |
| **RK-3** | LLM-judge non-determinism / prompt-injection via the judged reply or injected memory | 🟠 | Accepted-tracked | Advisory only (never a gate); injection-hardened judge prompt (reply + memory are fenced data); cheap model |
| **RK-4** | Carve-out removal breaks a real path not foreseen | 🟡 | In-design | R3 + removal tripwire + the 3 updated tests; grep confirmed only 4 tests and **no eval** depend on it |
| **RK-5** | The eval harness may not support a Copilot-channel scenario (scenarios are `textline` today) | 🟠 | Accepted-tracked (spike gates) | §6.3 spike **before** FR-3 sizing; if unsupported, harness plumbing bumps FR-3 S→M |
| **RK-6** | Actor-column ALTER on a live table | 🟡 | In-design | Nullable, no backfill, no read dependency until FR-4 lands (NFR-1) |
| **RK-7** | Scope creep into option D (propose→confirm) | 🟡 | Accepted-tracked | D explicitly non-goal / 0.0.3; promote only if UAT of the guarded path feels loose |

## 9. Decisions & dependencies

Resolved (2026-07-14, product-owner grill):

- **Source discriminator = `context.user_id` presence** (INTERNAL + actor →
  `employee_confirmed`; INTERNAL, no actor → `copilot_agent`).
- **Actor column nullable**; AI-draft and merge writes → null; UI correction → the
  rep's account id.
- **Carve-out removed**; the S15 characterization test **deleted**; the other three
  carve-out tests updated to assert `policy_blocked`.
- **Eval semantic legs = LLM-judge**, advisory (non-gating), injection-hardened,
  cheap model; `no-inferred` stays mechanical.
- **Option D deferred to 0.0.3.**
- **Product-owner sign-off = licai.**

Dependencies:

- Local Postgres for the datastore path (`docker compose up -d postgres` + migrate
  with `HERMES_APPLY_DEV_SEED`).
- The **eval-harness Copilot-channel spike** (§6.3 / RK-5) before FR-3 is sized and
  sliced.

## 10. References

- Exploration + grill outcomes: [workspace/0.0.2/EXPLORATION.md](EXPLORATION.md).
- 0.0.1 PRD (the shipped baseline this hardens): [workspace/0.0.1/PRD.md](../0.0.1/PRD.md).
- Deferred candidates: [workspace/0.0.3/EXPLORATION.md](../0.0.3/EXPLORATION.md).
- ADRs: 0111, 0112, 0114, 0140, 0142 (+ the one new governance ADR this iteration ships).
