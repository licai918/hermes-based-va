# 0.0.1 Product UAT sign-off — Customer Memory (M1)

- **Prepared by:** S15 (engineering evidence-gathering pass — this document does
  **not** itself constitute sign-off)
- **Prepared on branch:** `feat/0.0.1-customer-memory` @ `5e78af0` (S14 complete)
- **For:** licai (product owner, per PRD §9)
- **Scope:** §6.5 product acceptance criteria PAC-1…PAC-7 and the §6.6 product gate.
  PAC-8 (M2 grounded knowledge) is out of scope for 0.0.1 — see PRD §6.5 and the
  S15 issue brief.

## How to use this document

Technical green (PRD §6.0–§6.4, owned by S12/S13/S14) proves the plumbing is live
and correct. PAC-1…PAC-7 prove the customer/employee *experience* is better —
that is a judgment call only a human reading real transcripts can make. This
document maps each PAC to the automated evidence that exists today, marks
precisely what that evidence does and does not prove, and lists what still needs
your eyes before you sign. **Nobody has signed off on your behalf.** The
sign-off block at the bottom is empty and is yours to fill in after review.

---

## Part 1 — PAC-1…PAC-7 evidence map

| PAC | Criterion (PRD §6.5) | Automated evidence | What automation proves | What still needs YOUR review |
| --- | --- | --- | --- | --- |
| **PAC-1** | Preference honored *in behavior*, not merely stored | `eval/scenarios/25-customer-memory-honor-injected.yaml` (real-LLM recorded transcript: `eval/transcripts/text_first_launch/25.json`) — the scenario's *real* discriminating check is `text.must_not_contain` (the reply must not re-ask for a contact time); `hermes-runtime/tests/test_e2e_memory_acceptance.py::test_matrix_all_four_layers_live_in_one_run` — real Postgres round-trip: a preference written in turn 1 is byte-verified in the injected prompt of turn 2; `test_openrouter_memory_injection.py::test_verified_turn_injects_the_stored_preference_round_trip` | The stored value reaches the prompt unmodified, and a real model does not contradict/re-ask for it. **Caveat:** the scenario's `memory_assertions.honor_injected_preference: true` field looks like the relevant check but is not one — `eval_runner/turn_result.py` sets it to `True` unconditionally whenever the scenario has *any* `memory_preset`, regardless of transcript content (a pre-existing "freebie" flagged in S14's own report). The `must_not_contain` phrase list is the only assertion that actually inspects the reply text. | **This is the PAC with the sharpest human judgment call.** Transcript 25 shows the model *acknowledging* the preference in its reasoning but not overtly acting on it in the reply (a delivery-status answer, not an SMS follow-up offer). Transcript 28 (`28-customer-memory-merge-verified-wins.yaml`) is a *better* concrete example of overt action: *"I've got you down for after 2pm Eastern for any calls, so I'll keep that in mind going forward."* Decide: does "doesn't violate + doesn't re-ask" satisfy PAC-1, or do you want to see the assistant proactively *offer* the in-window follow-up as PRD's example text implies? Read both real transcripts and judge. |
| **PAC-2** | No over-recall / no creepiness; never claims unverified facts | None directly. Adjacent guards: eval 29 (adversarial injection-inert) and the `must_not_contain` lists in 25/27/28 catch specific *re-asking* phrases, not unprompted recitation | Nothing scripted currently asserts "the agent did not volunteer a stored preference out of the blue" | **Weakest automated coverage of all 7 PACs — no scenario targets this directly.** There is no eval scenario where the customer says nothing memory-related and we assert the agent stays silent about stored preferences. This needs a fresh read of transcripts (existing or a live run) specifically watching for unprompted recitation of preferences or unverified account claims. Recommend: if this matters for sign-off, ask engineering for one more scenario before you sign PAC-2, or accept transcript-only review as sufficient. |
| **PAC-3** | Unmatched → verified continuity, honored without re-asking | `test_e2e_memory_acceptance.py::test_provisional_to_verified_merge_chain` — real Postgres: provisional write → verified re-entry → merge fires → preference appears in the injected block, provisional rows deleted, exactly one merge-audit row; `eval/scenarios/28-customer-memory-merge-verified-wins.yaml` (real-LLM transcript, conflict sub-case: verified value wins over what the customer just said — the reply *text itself* explicitly restates the correct one, independent of the non-discriminating `honor_injected_preference` field noted under PAC-1) | The merge is atomic, idempotent, and the *content* carries forward correctly into the next prompt | The mechanical proof is strong. What needs a human: read a transcript of the actual customer-facing exchange across the two turns (a real "before verification" turn and the "after verification" turn back to back) and confirm it reads as *seamless* conversationally — not just that the assertion passed. |
| **PAC-4** | Employee sees + corrects a preference in Copilot; takes effect next turn | See **Part 2** below — this was the one open verification task in this brief | Driver-routing to Postgres is real (new test, real Postgres) | **This PAC cannot be walked through as a UAT today.** See Part 2 — there is no Workbench UI for it, and the one path that does exist has a binding-key defect for verified customers. This is not a "read the transcript and judge tone" gap; it is a "the feature is not usable yet" gap. |
| **PAC-5** | Never the wrong customer (≥2-customer walkthrough) | `test_e2e_memory_acceptance.py::test_cross_customer_isolation_both_directions` (2 verified customers, real Postgres, both directions — asserts customer B's *own* value is present **and** customer A's is absent, and vice versa); `test_customer_memory_datastore.py::test_get_preferences_never_leaks_across_binding_keys_either_direction`, `::test_load_customer_memory_never_leaks_across_binding_keys`, `::test_clear_preference_for_one_customer_does_not_touch_the_others_row`; `test_copilot_memory_injection.py::test_copilot_turn_never_sees_another_customers_block`; `eval/scenarios/27-customer-memory-isolation.yaml` (real-LLM transcript — the discriminating check is `text.must_not_contain` on customer A's phrase, same "freebie" caveat on `honor_injected_preference` as PAC-1 applies here too) | Strong, multi-level coverage: datastore query level, turn-injection level, and Copilot case level, all proven with real Postgres and presence-in-both-directions (not just absence) | This is the best-covered PAC. Your review here is more a confirmation pass than likely to surface a surprise: run (or read) the ≥2-customer UAT PRD asks for and confirm nothing outside the memory block (case lists, other tool reads) leaks cross-customer content — that surface is outside what these tests check. |
| **PAC-6** | Clean experience for a brand-new (no-memory) customer | `test_e2e_memory_acceptance.py::test_no_datastore_turn_replies_without_memory_artifact` (no-DB turn completes, no artifact); the matrix test's first-turn assertion (`"Customer Memory" not in captured[0]`) for a verified customer with no stored slots yet; `test_openrouter_memory_injection.py::test_memory_disabled_injects_no_memory_block`, `::test_unresolvable_binding_injects_no_memory_block_without_raising`; `eval/scenarios/26-customer-memory-no-inferred-write.yaml` transcript incidentally shows a clean reply with no memory artifact | No empty `"Customer Memory:"` block, no error, on every "nothing to inject" path tested (disabled, no binding, no slots, read error) | Read one real transcript for an actual brand-new customer end to end and eyeball it — specifically watch for the untrusted-data fence (S09's `<untrusted_customer_memory>` wrapper) ever leaking into a reply, which only a real model run can catch (scripted tests can't). |
| **PAC-7** | Write discipline felt (casual mention ≠ memory) | `eval/scenarios/26-customer-memory-no-inferred-write.yaml` (real-LLM transcript: an order-status question does not trigger a write — `forbid_inferred_upsert` + `forbidden_tools` both green); `hermes/tests/test_customer_memory_write_source.py`, `test_memory.py` (source is framework-set, never model-forgeable); S03 hard guards (only 4 slots, 200-char cap) | The `source` field cannot be forged, and one concrete "not a preference" scenario doesn't over-trigger | Scenario 26 is one scripted near-miss (an order-status question). A human should skim a broader UAT set for subtler phrasings — casual asides, hypotheticals ("I usually prefer mornings but today's fine") — that the one scripted scenario doesn't cover, and confirm the agent doesn't write on those either. |
| **PAC-8** | (M2) Grounded knowledge | Out of scope — belongs to 0.0.2 per PRD §6.5 footer and the S15 issue brief's "Out of scope" | — | — |

**On the eval transcripts:** `eval/transcripts/text_first_launch/24.json` through `29.json` are genuine recorded real-model runs (they carry model `reasoning_content`/`reasoning_details`, not hand-written stub text) — they are legitimate material for your PAC-1/2/6/7 reads, not placeholder fixtures. You do not need a fresh live demo to start; reading these six is a reasonable first pass. If you want fresher or more diverse transcripts (different phrasing, different customers), ask engineering for a live run.

---

## Part 2 — PAC-4 verification (the open question this brief was asked to resolve)

**Question:** does an employee (Copilot) preference correction actually persist to
Postgres `customer_memory_slot`, and does it reach the row the customer's own next
turn will read?

### What exists today

There is **no Workbench UI surface for this at all yet.** A repo-wide search of
`apps/workbench` (components, API routes, BFF layer) for `preference`,
`customer_memory`, `upsert_preference`, `channel_identity_id` returns zero
matches. The case-detail API routes that do exist
(`apps/workbench/app/api/copilot/cases/[id]/*`) cover assign/claim/priority/
resolve/contact-reason/audit-log/thread — nothing preference-related. **PAC-4's
UI half (a rep sees + clicks to correct a preference) is unbuilt**, independent
of the backend question below.

### The backend path, traced precisely

Two distinct code paths can reach `toee_customer_memory.upsert_preference` on the
Internal Copilot profile. They fail in different ways:

**(a) The deterministic dispatch route — what the brief named**
(`tool_dispatch_composition.py` → `tool_dispatch_app.py`'s `POST /v1/tools:dispatch`,
what a Workbench "click to correct" button would call):

- `tool_dispatch_composition.build_tool_dispatch_app()` calls
  `select_tool_driver()` once and shares it across the dispatch route. With
  `TOOL_BACKEND=datastore`, that resolves to a **full `PostgresDriver`**
  (`hermes_runtime/tool_backend.py`), not a partial overlay — its registry
  (`build_datastore_registry()`) includes `memory_handlers()`
  (`hermes_runtime/datastore/handlers/memory.py`), which does a real
  `INSERT ... ON CONFLICT DO UPDATE` into `customer_memory_slot`. **The driver
  routing is correct: the write really lands in Postgres.**
- However, `dispatch()` in `tool_dispatch_app.py` builds
  `ToolExecutionContext(profile=profile, user_id=actor_account_id)` — it **never
  sets `.identity`** (only `tool`/`action`/`params`/`actor_account_id` are read off
  the request body). `ToolExecutionContext.identity` defaults to `None`
  (`toee_hermes/tool_gate.py`).
- With `context.identity` always `None` on this route, the shared binding
  resolver (`resolve_customer_memory_binding`, imported identically by both the
  mock and Postgres handlers, in `toee_hermes/drivers/mock/memory.py`) falls
  through to its `internal_copilot`-only fallback: it reads a
  `channel_identity_id` param and returns `f"provisional:{channel_identity_id}"`
  **unconditionally** — there is no way through this fallback to produce the bare,
  unprefixed key a **verified** customer is bound to.
- The customer's own next external turn reads memory via
  `binding_key_from_identity(identity)` (`openrouter.py::_load_turn_memory`),
  which for a verified customer returns the **bare `shopify_customer_id`, no
  prefix**. For a provisional/unmatched customer it returns the 3-part
  `provisional:{channel}:{E.164}` — also not what the 2-part
  `provisional:{channel_identity_id}` fallback produces unless the caller happens
  to pass exactly `"{channel}:{E.164}"` as `channel_identity_id` (undocumented,
  and nothing in the codebase constructs that value today).

**Net effect for a verified customer (the primary, realistic UAT scenario — the
same "returning verified customer" PAC-1/3/5 all use):** the correction **is
genuinely written to Postgres** (not a mock, not a no-op) but under a
`"provisional:..."` key that the customer's next turn will never read. The rep
would see "saved," and the customer would never see the change. This is now
**proven with a real-Postgres test**, not just a code trace:

> `hermes-runtime/tests/test_datastore_driver_memory.py::test_dispatch_route_correction_persists_but_misses_a_verified_customers_read_key`

The test reproduces the exact dispatch-route contract (profile
`internal_copilot`, `identity=None`, `channel_identity_id` = the case's Shopify
customer id — the only case-identifying value that route has), writes through
the real `PostgresDriver`, confirms the row is genuinely in `customer_memory_slot`
under `provisional:{shopify_customer_id}`, and then confirms a `get_preferences`
call using the verified identity (the shape the customer's own next turn uses)
comes back **empty**.

**(b) The Copilot AI-agent draft turn** (`copilot_turn.py`'s
`make_copilot_run_turn`, the LLM route mounted at `agent:turn` on the same
server) — this is the path `.superpowers/sdd/progress.md`'s S08 note flagged
("doesn't pass `extra_drivers`"). Confirmed by code trace: it boots via
`boot_profile(INTERNAL, identity=identity)` with **no `conversation_id`**, which
calls the plugin's unbound `register()` — and `register()` has **no
`extra_drivers` parameter at all** (only `register_turn`, the bound external-turn
path, does). Its base driver selector (`_build_driver_selector` in
`toee_hermes/plugin/__init__.py`) resolves off `INTEGRATION_DRIVER` (a different
axis, for external vendors), never `TOOL_BACKEND` — so if the copilot AI agent
itself ever called `upsert_preference` mid-draft, it would **always** hit the
ephemeral in-process `MockDriver`, regardless of any env var. This path
correctly threads `context.identity` (so *if* it reached Postgres, the binding
key would be right) — it is the mirror-image defect of (a).

### Verdict

**PAC-4 employee-write persistence: needs-fix — not a simple "works" or "add
`extra_drivers` and done."** Two independent, narrow gaps, neither of which is
just the `extra_drivers` addition progress.md flagged:

1. Path (a), the real dispatch-route mechanism, persists to the right *store*
   but the wrong *key* for a verified customer. Fixing this needs the dispatch
   route to resolve real case identity before calling the tool (e.g. accept a
   `case_id` and call the already-existing `PostgresGatewayStore.load_case_identity`
   the way `copilot_turn.py` does, populating `ToolExecutionContext.identity`) or
   an explicit, separately-governed verified-customer param — a binding-key
   design decision, not a one-line fix, and security-sensitive (this is the exact
   fail-closed binding logic RK-3/FR-5 hardened elsewhere in this milestone).
2. Path (b), the AI-agent draft turn, is structurally mock-only and *would* need
   the `extra_drivers` threading progress.md flagged, but **only if** you want
   "ask the copilot chat agent to correct it" to be a supported mechanism rather
   than a deterministic UI action.
3. Neither matters yet in practice because **the Workbench UI has no surface for
   this feature at all** — there is nothing today for a rep to click.

None of this was implemented as part of S15 — S15's brief is verification and
evidence-gathering, not a fix. This is flagged as a follow-up (see the spawned
task).

---

## Part 3 — Explicit "needs human review before sign-off" list

In priority order:

1. **PAC-4 cannot be signed off as-is.** The UAT walkthrough PRD asks for ("a rep
   opens a case, sees preferences, corrects one, it takes effect next turn") is
   not currently possible to perform — there is no UI, and the one reachable
   backend path writes to a key the customer's next turn won't read for a
   verified customer. You will need to decide: waive/defer PAC-4 for the 0.0.1
   gate, or hold the gate until the two gaps in Part 2 are fixed and a real UI
   exists.
2. **PAC-2** has no automated evidence targeting it directly (no scenario checks
   "does the agent stay quiet about memory when unprompted"). Read transcripts
   with this specifically in mind, or ask for one more scenario before signing.
3. **PAC-1** — read transcripts 25 and 28 side by side
   (`eval/transcripts/text_first_launch/`) and decide whether "doesn't
   contradict / doesn't re-ask" clears the bar, or whether you want to see more
   overt proactive action like transcript 28's.
4. **PAC-3, PAC-6, PAC-7** — well-covered mechanically; a transcript skim is a
   confirmation pass, not expected to surface a surprise.
5. **PAC-5** — best-covered PAC; confirm the ≥2-customer walkthrough and that
   nothing *outside* the memory block leaks cross-customer content (out of scope
   for the existing tests).
6. Two engineering escalations already on record in
   `.superpowers/sdd/progress.md` (S13/S14) are **not re-litigated here** but are
   relevant context for how much weight to put on "green" claims longer-term:
   the memory write/merge audit trail diverges from PRD §6.4's literal
   `workbench_audit_log` wording (slot metadata + a dedicated merge-audit table +
   structured logs instead), and CI provisions no Postgres today, so the
   datastore/E2E acceptance gate is only enforced locally, not in CI. Both are
   already flagged for you elsewhere; listed here only so this document doesn't
   read as if they don't exist.

---

## Sign-off

**Nothing below this line has been filled in.** Per PRD §9, product-owner sign-off
on the §6.6 product gate is licai.

| PAC | Accepted? (Y / N / Waived) | Notes | Date |
| --- | --- | --- | --- |
| PAC-1 | | | |
| PAC-2 | | | |
| PAC-3 | | | |
| PAC-4 | | | |
| PAC-5 | | | |
| PAC-6 | | | |
| PAC-7 | | | |

**Overall 0.0.1 product gate (PRD §6.6):**

- [ ] PAC-1…PAC-7 accepted on a UAT transcript pass across ≥2 customers,
      including one unmatched→verified continuity case and one Copilot
      correction (or explicitly waived, with reason, above).

Signed: ______________________________  (name)

Date: ______________________________
