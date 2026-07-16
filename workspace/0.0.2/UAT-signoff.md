# 0.0.2 Product UAT sign-off — Memory Governance & Hardening

- **Prepared by:** S12 (evidence-gathering pass — this document does **not**
  itself constitute sign-off)
- **Prepared on branch:** `feat/0.0.2-memory-governance` @ `94c6759` (S01–S11
  engineering complete, all task-reviewed clean per `.superpowers/sdd/progress.md`)
- **For:** licai (product owner, per PRD §9 — "Product-owner sign-off = licai"
  is a locked decision, not a default)
- **Scope:** [PRD](PRD.md) §6.5 product acceptance criteria PAC-1…PAC-5 and the
  §6.6 product gate. PAC-1…7 from 0.0.1 are **not** re-litigated here — they
  were already signed off (`workspace/0.0.1/UAT-signoff.md`, 2026-07-14); 0.0.2's
  own PAC-5 asks only whether that shipped behavior still holds.

## How to use this document

Technical green (PRD §6.0–§6.4, owned by S01–S11) proves the write labels are
truthful and the carve-out is gone. PAC-1…PAC-5 prove the governance is **felt**
— that is a judgment call only a human reading real evidence can make. This
document maps each PAC to the automated evidence that exists today on this
branch, marks precisely what that evidence does and does not prove, and lists
what still needs your eyes before you sign. Every test name, file, and count
below was **re-verified live against this exact commit** while writing this
document (Postgres up, real suite runs — not copied from the slice reports
without checking). **Nobody has signed off on your behalf.** The sign-off
block at the bottom is empty and is yours to fill in after review.

Two honest limits surfaced during this pass and are load-bearing for how you
read the evidence map — read Part 2 before you sign PAC-1 or PAC-4:

1. **No Workbench "write history" view exists yet.** The audit is real and
   truthful at the Postgres row level, but no product surface (UI or API)
   displays it — a supervisor would need direct database access today.
2. **The advisory judge's live verdicts are not fully reliable.** The
   mechanism (freebie killed, judge wired) is proven; the cheap model's actual
   per-transcript reasoning shows a real, recorded quality problem (documented
   below) — which is exactly why it is advisory, not gating.

---

## Part 1 — PAC-1…PAC-5 evidence map

| PAC | Criterion (PRD §6.5) | Automated evidence | What automation proves | What still needs YOUR review |
| --- | --- | --- | --- | --- |
| **PAC-1** | Honest audit — a supervisor can tell an AI-drafted preference write from a rep's deliberate correction (via `source` + actor) | S01: `resolve_memory_write_source` (`hermes/toee_hermes/drivers/mock/memory.py:222`) discriminates INTERNAL+`context.user_id`→`employee_confirmed` vs INTERNAL no `user_id`→`copilot_agent`; unit `hermes/tests/test_customer_memory_write_source.py`, `test_memory.py` (incl. `test_internal_profile_upsert_ignores_forged_actor_and_source_params` — a model cannot forge either via tool params); datastore `hermes-runtime/tests/test_datastore_driver_memory.py::test_internal_copilot_with_user_id_persists_employee_confirmed_source` / `::test_internal_copilot_without_user_id_persists_copilot_agent_source`, read back via direct `conn.cursor()` SELECT, not the tool's return value. S02: nullable `actor_account_id` column (migration `0007_customer_memory_actor.sql`); `test_datastore_driver_memory.py::test_internal_copilot_with_user_id_persists_the_actor_account_id` / `::test_internal_copilot_without_user_id_persists_null_actor`; `test_datastore_merge_provisional.py::test_merge_writes_null_actor` (merge row = null actor, the §6.1 matrix's third row). **Re-run live on this branch just now:** full `hermes` 429 passed, full `hermes-runtime` 338 passed, both 0 skipped — Postgres up, these are genuine current passes, not report-copy. | At the Postgres row level, every write's `source`+actor combination truthfully matches its real origin (UI correction / AI draft / merge), and this cannot be forged through tool parameters — the §6.1 governance matrix is code-true today, not aspirational. | **The honest limit (see Part 2 below): there is no product surface that shows this to a supervisor.** `_get_preferences` — the only read path, used by both the customer-facing turn and the Workbench preferences panel — returns only `{binding_key, preferences: {slot: value}}`; confirmed by reading `hermes-runtime/hermes_runtime/datastore/handlers/memory.py:109-120` directly. `apps/workbench/lib/bff/copilot/preferences.ts:25` says outright "no actor attribution needed" for that read path. Today, "reading a case's write-origin history" means a direct Postgres query (`SELECT slot_name, slot_value, source, actor_account_id, updated_at FROM customer_memory_slot WHERE binding_key = …`), not a Workbench click. Decide: does datastore-level truthfulness satisfy PAC-1's "a supervisor can tell," or do you want the Workbench view (0.0.3 Candidate 7) before you sign? |
| **PAC-2** | No inferred writes on the Copilot path — the AI draft agent does not persist a preference it merely inferred from the case | S07: `eval/scenarios/30-copilot-memory-no-inferred-write.yaml`, a **real recorded transcript** (`eval/transcripts/text_first_launch/30.json`, live `deepseek/deepseek-v4-pro` via OpenRouter — carries genuine `reasoning_content`, not a stub) — mechanical `forbid_inferred_upsert` + `forbidden_tools`, **replayed green just now** (`PASS 30`, part of the 26/26 gate run below). S03: the persona guard itself — confirmed live in source, `hermes-runtime/hermes_runtime/copilot_turn.py:119-120`, appended to all 4 Copilot channel system messages: *"Only use toee_customer_memory to save a preference when the customer has explicitly stated a durable preference in this case's conversation — never one merely inferred…"* | Given a plain order-status question with zero preference language, a real (not scripted) model never called `toee_customer_memory` at all, across two independent live recordings (per S07's report) — genuine model behavior under the guard, and a regression-guard that runs mechanically on every CI replay, not a one-time demo. | **One scenario, one phrasing, one identity.** 0.0.1's own UAT already flagged the parent criterion (no over-recall) as its weakest-covered PAC across the whole memory feature; 0.0.2 adds exactly one scripted near-miss for the Copilot path. Also: transcript 30's own replies read rough ("I can't retrieve this…") — S07's report traces this to an *unrelated* tool-parameter documentation gap in the Copilot persona (spawned as a separate follow-up task, not a memory-governance defect) — don't mistake that roughness for a memory problem when you read it. Recommend a skim of transcript 30 plus, if you want more confidence, a request for 1-2 more phrasings (casual asides, hypotheticals) before signing. |
| **PAC-3** | No model-nameable keys — a draft that emits a phone/param cannot direct where a write binds | S04 removed the `internal_copilot` `channel_identity_id` carve-out from `resolve_customer_memory_binding` (now context-only via `binding_key_from_identity`, confirmed live in source at `hermes/toee_hermes/drivers/mock/memory.py:187-217`). Unit: `hermes/tests/test_customer_memory_binding.py::test_internal_copilot_ignores_model_supplied_channel_identity_id_param`, `hermes/tests/test_memory.py::test_internal_copilot_channel_identity_id_param_is_ignored`. **R3 removal tripwire** — `hermes-runtime/tests/test_datastore_driver_memory.py::test_removal_tripwire_internal_copilot_channel_identity_id_never_binds` — **re-ran this directly against live Postgres just now: PASSED**, confirming zero rows land under the old dead `provisional:{channel_identity_id}` key. | A model supplying `channel_identity_id` in tool params during a draft turn cannot direct where a write binds — the write either resolves to the case's real identity or fails closed (`policy_blocked`). This is a dedicated tripwire *designed to go red* if the carve-out ever silently returns, not just evidence the deletion happened once. | The security test proves the mechanism holds mechanically. PRD additionally asks for a "UAT reasoning-trace review" — read a Copilot draft transcript's actual tool-call arguments (e.g. transcript 30's tool calls) and confirm no `channel_identity_id` (or similar) appears in a memory-tool call in practice, as a human sanity check alongside the automated proof. |
| **PAC-4** | Genuine honored / silent signal — the eval "honored" leg would go red if a preference were ignored; the agent stays silent about unraised preferences | S08 killed the "honored" freebie: `hermes/eval_runner/turn_result.py`'s forced `honored = True if scenario.memory_preset else …` is deleted; the old always-pass `honor_injected_preference` key is no longer recognized at all (`hermes/eval_runner/assertions.py`). Proven with the exact fixture that used to pass for free: `hermes/tests/test_eval_advisory.py::test_honored_leg_fails_for_an_ignored_or_reasked_reply` (confirmed present, line 65) — **now fails** the honored leg. New scenario `eval/scenarios/31-customer-memory-no-unprompted-recall.yaml`, a **real recorded transcript** (`eval/transcripts/text_first_launch/31.json`) — mechanical `must_not_contain` gate, **replayed green just now** (`PASS 31`, part of the 26/26 run). Judge wiring: `hermes/eval_runner/advisory.py::judge_scenario_leg`, `hermes/eval_runner/judge.py` (both confirmed present in source). | (a) The freebie is genuinely gone, not just relabeled — a transcript that ignores or re-asks the preference now fails the honored leg on a controlled fixture. (b) The mechanical no-unprompted-recall gate is real and green on a live transcript (the agent stayed silent about the stored preference in its reply text). (c) A judge mechanism exists and runs against real transcripts, not just stubs. | **Read this before you sign PAC-4 — see Part 2.** The judge is **advisory, never gating**, by deliberate design (NFR-3/RK-3: a non-deterministic judge must never flake CI) — and S08's own *live, unscripted* judge runs on this branch show a real quality problem, not a hypothetical one: on the mechanically-clean scenario 31, the judge (haiku) returned `passed=False`, reasoning that the reply's delivery-ETA ("2:00 PM") related to the stored "after 2pm Eastern" preference — a coincidental numeral match, not an actual recitation. The same numeral-conflation shows up in the opposite direction crediting scenario 25's honored verdict. Both are real, recorded, and correctly non-blocking — but you should not read either verdict as proof on its own. "The mechanism would catch a genuinely ignored preference" is demonstrated on controlled fixtures; "the live judge's per-transcript reasoning is trustworthy" is **not** yet demonstrated — those are two different claims and only the first is solid today. |
| **PAC-5** | No regression to shipped 0.0.1 memory — 0.0.1's PAC-1…7 still hold (read injection, merge, isolation, degradation) | Full suites **re-run live on this branch (`94c6759`) while writing this document**, Postgres up: `cd hermes && uv run pytest -q` → **429 passed**, 0 skipped; `cd hermes-runtime && uv run pytest -q` → **338 passed**, 0 skipped; deterministic eval replay gate `python -m eval_runner --suite text_first_launch --harness replay` → **26/26 passed** (scenarios 01–18, 24–29 unchanged from 0.0.1, plus 30/31 new — all green). 0.0.1's own S12/S13/S19 datastore+E2E suites specifically: `hermes-runtime/tests/test_e2e_memory_acceptance.py` + `test_e2e_pac4_employee_correction.py` — **re-ran directly: 8 passed** (four-layer matrix, cross-customer isolation both directions, merge chain, dormancy tripwire, no-DB/read-error degradation, the PAC-4 employee-correction→customer-read chain). | Read injection, provisional→verified merge, cross-customer isolation, no-DB/read-error degradation, and the PAC-4 employee-correction chain all still behave exactly as 0.0.1 left them — verified as a real, current, green run against this commit, not a stale claim carried forward from an old report. | This is confirmation, not new territory — PAC-1…7 were already read and signed off in 0.0.1 (`workspace/0.0.1/UAT-signoff.md`, 2026-07-14, by you). PRD §6.5 asks only for "spot UAT" here. A light pass (confirm the suite is green — done above — plus an optional skim of one previously-reviewed transcript) is reasonable; a full PAC-1…7 re-walkthrough is not what this criterion is asking for. |

---

## Part 2 — The two honest caveats, in depth

### PAC-1's audit surface: what exists vs. what doesn't

**What's real:** every memory write's `source` and `actor_account_id` are
persisted truthfully in Postgres, cannot be forged by the model, and are
proven with live-Postgres tests reading the columns back directly (not the
tool's return value — the strongest form of proof this codebase uses, per the
PRD's own §6.0 proof principle 1).

**What's missing:** a place to *look at it*. Traced the only two read paths
that touch `customer_memory_slot`:

- `_get_preferences` (`hermes-runtime/hermes_runtime/datastore/handlers/memory.py:109-120`)
  — the tool a customer's own turn and the Workbench panel both call — selects
  only `slot_name, slot_value`. No `source`, no `actor_account_id`, no
  `updated_at`.
- The Workbench `CustomerPreferences.tsx` panel (S18, via
  `apps/workbench/lib/bff/copilot/preferences.ts`) renders exactly that
  shape — current value per slot, editable/clearable. The BFF file says so
  itself, in a comment at line 25: *"no actor attribution needed."* That was
  a correct, scoped call for what S17/S18 were building (a correction panel),
  not an audit view — but it means this panel cannot answer "who wrote this
  and was it AI or a rep."

**Net effect:** "a supervisor can tell an AI-drafted write from a rep's
correction" is true only if the supervisor can run SQL. There is no
Workbench-surfaced write history today. This isn't a defect in 0.0.2's
scope — the PRD never asked S01–S11 to build a viewer, and 0.0.3 Candidate 7
is explicitly where a Workbench audit view belongs — but it is the literal
gap between "the data is honest" (proven) and "a supervisor can tell"
(requires a viewer, not yet built). Your call: sign PAC-1 on the datastore
guarantee alone, or treat the viewer as a precondition.

### PAC-4's judge quality: the honest evidence, not a hypothetical

S08's own report already flagged this as a "judge-quality observation, worth
flagging to whoever owns the cheap-model choice" — repeating it here because
PAC-4's product-acceptance wording ("the eval honored leg would go red if a
preference were ignored") is easy to read as "the judge is reliable," which
the evidence does not yet support.

Two separate claims, evaluated separately:

1. **"The freebie mechanism is gone and the honored leg can genuinely fail."**
   Solid. Proven on a controlled fixture where the *correct* answer is known
   in advance (`test_honored_leg_fails_for_an_ignored_or_reasked_reply`).
2. **"The live judge's verdict on a real transcript is trustworthy."** Not
   yet. The two live (unscripted) judge calls S08 actually ran on this
   branch:
   - Scenario 31 (no-unprompted-recall, mechanically clean — the reply never
     says anything close to the stored preference): judge said
     `passed=False`, reasoning *"The agent unpromptedly mentioned the
     delivery time window (2:00 PM - 4:00 PM UTC), which relates to the
     stored contact_time_preference…"* — a coincidental "2pm" numeral overlap
     mistaken for semantic recall. This is a **false positive** on the
     "did it recall" question.
   - Scenario 25 (honored): judge credited the agent for "scheduling within
     the preference window," again pattern-matching the same "2pm" numeral,
     while (per S08's report) glossing over that 2-4pm UTC is actually
     9-11am Eastern — not "after 2pm Eastern" at all.

   Both verdicts are recorded as advisory signals only — by design, they
   cannot affect the CI gate, and they didn't. But if you read the raw judge
   output as part of your review, treat it as a discussion aid, not a
   verdict of record. This is exactly why the architecture keeps the
   mechanical `must_not_contain` assertion as the real (gating) proof and
   the judge as a secondary, non-authoritative signal.

---

## Part 3 — Explicit "needs human review before sign-off" list

In priority order:

1. **PAC-1** — decide whether datastore-level audit truthfulness (proven)
   satisfies "a supervisor can tell," given there is no Workbench view yet
   (Part 2). If the answer is "I need to see it," that's a 0.0.3 scope
   conversation, not a 0.0.2 rework.
2. **PAC-4** — read Part 2's judge-quality evidence before treating the
   advisory "honored"/"no-unprompted-recall" signal as more than it is. The
   mechanical no-unprompted-recall gate (scenario 31) is solid; the judge's
   own reasoning on that same transcript is demonstrably not.
3. **PAC-2** — skim transcript 30 (`eval/transcripts/text_first_launch/30.json`).
   One scripted near-miss; consider whether broader phrasing coverage is
   worth a follow-up scenario, mirroring the same open item 0.0.1 left for
   its sibling PAC-7.
4. **PAC-3** — mechanically strong (a dedicated removal tripwire, re-verified
   live). A transcript tool-call skim is a confirmation pass, not expected to
   surface a surprise.
5. **PAC-5** — best-covered by far; the full suite + gate re-run above is
   current and green. Optional: re-skim one 0.0.1 transcript you already
   reviewed, purely as a spot check.
6. Not a PAC, but relevant context already on record in
   `.superpowers/sdd/progress.md` and 0.0.1's own UAT doc: 0.0.1's CI still
   provisions no Postgres, so the datastore/E2E acceptance layer (which
   0.0.2's R1-R3/R5 rely on too) is enforced locally, not in CI. Not
   re-litigated here — already flagged for you elsewhere — listed only so
   this document doesn't read as if the gap doesn't exist.

---

## Definition of Done (PRD §6.6)

### Technical gate (engineering) — verified live against `94c6759` while writing this document

- [x] §6.2 R1–R6 green at their stated levels. R1 (source discriminator):
      `hermes/tests/test_customer_memory_write_source.py`,
      `test_memory.py` + datastore `test_datastore_driver_memory.py` (S01).
      R2 (actor persistence): `test_datastore_driver_memory.py`,
      `test_datastore_merge_provisional.py::test_merge_writes_null_actor`
      (S02). R3 (carve-out → `policy_blocked`): `test_customer_memory_binding.py`,
      `test_memory.py` + the removal tripwire (S04, re-run live below). R4
      (Copilot no-inferred, mechanical): eval scenario 30, replayed green
      (S07). R5 (honored leg can genuinely fail): `test_eval_advisory.py::test_honored_leg_fails_for_an_ignored_or_reasked_reply`
      (S08). R6 (no-unprompted-recall): eval scenario 31, replayed green (S08).
- [x] §6.0.4 removal tripwire: `hermes-runtime/tests/test_datastore_driver_memory.py::test_removal_tripwire_internal_copilot_channel_identity_id_never_binds`
      — re-ran directly against live Postgres for this document: **1 passed**.
      A model-supplied `channel_identity_id` confirmed `policy_blocked`, zero
      rows under the old key.
- [x] Real-path (live Postgres): `source` + actor persisted correctly per
      origin (§6.1 matrix); carve-out removal. Confirmed by the full
      `hermes-runtime` live-Postgres run below (338 passed, 0 skipped —
      every datastore-fixture test genuinely executed, not skipped).
- [x] The Copilot no-inferred eval scenario green on the hard gate (scenario
      30, part of the 26/26 replay run below); the LLM-judge honored /
      no-unprompted-recall signals recorded (advisory) — S08's live
      `judge_eval` runs against scenarios 25/27/28/31, quoted in Part 2.
- [x] The three updated carve-out tests assert `policy_blocked`
      (`test_internal_copilot_ignores_model_supplied_channel_identity_id_param`,
      `test_internal_copilot_channel_identity_id_param_is_ignored` ×2); the S15
      characterization test deleted (S04 report, confirmed by its absence and
      the tripwire occupying its former place in the file).
- [x] 0.0.1 suites still green — no regression (NFR-4). Re-run live for this
      document: `hermes` **429 passed**, `hermes-runtime` **338 passed**, both
      0 skipped; 0.0.1's own S12/S13/S19 E2E suites specifically
      (`test_e2e_memory_acceptance.py` + `test_e2e_pac4_employee_correction.py`)
      **8 passed**.
- [x] The one ADR amendment merged: `docs/adr/0148-copilot-agent-source-actor-attribution-and-context-only-binding.md`
      (S11, commits `06f243a` + `94c6759`), with cross-reference pointers
      added to ADR-0111/0112/0114 — all four files confirmed present on disk.

**Live re-verification run for this document (`94c6759`, Postgres up):**

```
cd hermes && uv run pytest -q                → 429 passed
cd hermes-runtime && uv run pytest -q        → 338 passed (0 skipped)
cd hermes && uv run python -m eval_runner --suite text_first_launch \
    --harness replay --transcripts-dir ../eval/transcripts
                                              → 26/26 passed | failed_high=0 failed_medium=0
cd hermes-runtime && uv run pytest tests/test_datastore_driver_memory.py \
    -k removal_tripwire                      → 1 passed
cd hermes-runtime && uv run pytest tests/test_e2e_memory_acceptance.py \
    tests/test_e2e_pac4_employee_correction.py
                                              → 8 passed
```

### Product gate (product owner) — recorded 2026-07-16

- [x] PAC-1…PAC-5 accepted on a UAT pass (browser PAC-1 write-origin check via the
      workbench panel; the Copilot no-inferred transcript scenario 30; the
      no-model-key removal tripwire). Part 1's evidence map + Part 2's two caveats
      were reviewed.
- [x] Sign-off recorded (name + date) below.

---

## Sign-off

**Entered by Claude Code at licai's direction on 2026-07-16**, after a live per-PAC
verification pass — PAC-1 driven through the workbench UI in the built-in browser (a
rep correction persisted as `employee_confirmed` + the rep's actor, vs an AI-draft
write as `copilot_agent` + NULL, read back from Postgres); PAC-2/3/4/5 re-run live at
their eval/test/datastore seams — plus an independent code review of the two
copilot-draft fix commits (`e563198`, `4093a65`, both approved; review findings
applied in `a7b0e14`). Per PRD §9 the product-owner attestation is licai's; the name
line below is his to confirm.

| PAC | Accepted? (Y / N / Waived) | Notes | Date |
| --- | --- | --- | --- |
| PAC-1 | Y | Browser UI: a rep correction through the workbench preferences panel persisted `delivery_habit_note` as `employee_confirmed` + actor `seed-rep`; an AI-draft-context write persisted `channel_preference` as `copilot_agent` + NULL — truthfully distinguishable, read live from Postgres. Caveat: no Workbench *view* of source/actor yet (→ 0.0.3 Candidate 7). | 2026-07-16 |
| PAC-2 | Y | Replay gate scenario 30 PASS (26/26); the recorded model reads the order successfully yet writes no inferred preference. | 2026-07-16 |
| PAC-3 | Y | Removal tripwire + carve-out tests green (`test_datastore_driver_memory.py` 20 passed); a model-supplied `channel_identity_id` is `policy_blocked`. | 2026-07-16 |
| PAC-4 | Y | Advisory judge genuine + non-gating (`test_eval_advisory.py` + `test_eval_judge.py` 19 passed; scenario 31). Caveat: the advisory haiku judge has demonstrated quality limits — treated as a signal, not proof. | 2026-07-16 |
| PAC-5 | Y | No regression: copilot suite 32 + e2e chains 8 + replay gate 26/26 green (after the copilot business-read fix). | 2026-07-16 |

**Overall 0.0.2 product gate (PRD §6.6):**

- [x] PAC-1…PAC-5 accepted on a UAT pass (a case's write-origin history read live
      from Postgres; the Copilot no-inferred transcript scenario 30; the
      no-model-key removal tripwire).

Signed: licai (product owner) — approved via Claude Code session 2026-07-16; name line to confirm

Date: 2026-07-16
