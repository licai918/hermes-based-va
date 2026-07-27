# 0.0.5 — pre-flight decisions (binding overlay on the slice briefs)

Produced by an adversarial pre-flight scan of the PRD and all 29 slice files against the real
code, run before any 0.0.5 implementation. It found **9 slice-to-slice contradictions, 12
review-rubric conflicts, and 11 blocking risks**. Every one is resolved below.

**These decisions bind.** Where a decision contradicts the text of a slice brief, the decision
governs; each affected brief carries a "Pre-flight corrections" block naming the decisions that
apply to it. Global decisions (numbering, naming, scanner policy, hotspot ordering) live only
here.

Two decisions are **owner calls** where a default has been taken so work is not blocked:
**D11** (S27's missing input) and **D14** (the knob panel's audit path). Both are reversible.

---

## D0. Reading the slice files — bare S-numbers

The briefs reference other slices by bare number in two different senses: **0.0.5** slices (the
plan being executed) and **0.0.3/0.0.4** slices (shipped history, cited as the pattern to
copy). A fresh reader cannot tell them apart, and two of them read as dependency cycles that do
not exist.

**Rule: inside `workspace/0.0.5/`, a bare `Sxx` ALWAYS means the 0.0.5 slice.** Every reference
to a previous iteration is written `Sxx-0.0.3` / `Sxx-0.0.4`. Known cases:

| Reads as | Actually means |
| --- | --- |
| S01 "S22-scanned on write" | the scanner shipped by **S22-0.0.3** (`scan_agent_experience_content`) |
| S01 "S14 result-extraction" | the envelope shipped by **S14-0.0.3** |
| S01/S02 "draft-turn-inert (S25 pattern)" | **S25-0.0.3** |
| S18 "the S26-0.0.3 metric_event pattern" | already qualified — correct as written |
| S19/S20 "S04 worker pattern" | **S04-0.0.4** (the durable job-queue worker) |
| S24 "S32 fold-in" | **S32-0.0.3**, folded into this iteration's S24 |
| NFR-7 "the S15/S21 lesson" | **S15-0.0.4 / S21-0.0.4** mock/PG drift |

## D1. Migration numbers — allocated once, up front

The 0.0.4 mainline now tops out at `0019_draft_feedback.sql` (quality-feedback merged via
PR #68 and folded into this branch). **The 0.0.5 floor is 0020.** Numbers are allocated here so
two slices never race for one prefix; a slice that turns out not to need its number leaves a
hole.

| Prefix | Slice | Table / change |
| --- | --- | --- |
| 0020 | S01 | `semantic_lexicon` — **LANDED** |
| 0021 | ~~S09~~ **S21** | `honored_rate_leg_results` — **LANDED**. S21 needed a table this table did not anticipate (its Surface line declared none) and reached 0021 first. Rewriting a landed migration is worse than moving an unwritten one, so **S09 moves to 0030**. |
| 0022 | S15 | `review_item` |
| 0023 | S18 | latency samples (D5 — S18 DOES need a migration) |
| 0024 | S03 | seeded domain #1 rows |
| 0025 | S13 | proposal `annotations` JSONB (D8) |
| 0026 | S05 | lexicon hit accounting (D6) |
| 0027 | S25 | aggregator watermark |
| 0028 | S26 | effectiveness rollup |
| 0029 | S27 | `draft_feedback.sent_text` (D11 — owner-flagged) |
| 0030 | **S09** | `injection_ledger` + its query indexes — **moved here from 0021**, see above |
| 0031 | spare | |

The 0021 collision is the reason this table exists, and it still happened — because the table
only allocates numbers to slices the plan predicted would need one. **If your slice needs a
migration and this table gives you no number, take the next free prefix, and say so loudly in
your report** so the table can be corrected before the next slice reads it.

Still re-verify by listing the directory before writing yours; if reality has moved past this
table, take the next free number and say so in the report.

## D2. The write scanner must be SPLIT — it currently rejects the iteration's own demo

`scan_agent_experience_content` hard-rejects **both** injection patterns and PII patterns
(email / phone / Shopify customer id). Two consequences make it unusable as-is for 0.0.5:

1. `_PHONE_RE = \+?\d[\d\-\s]{6,14}\d` **matches `205 55 16`** — literally the flagship seeded
   `surface_form` of S03/S05/US2/PAC-1. Unsplit, the seed path, S04's capture fork, and
   S25/S27's emissions are all `policy_blocked` on the headline demo of the iteration.
2. **L4 is the PII layer by design** (NFR-6: "L4 PII stays bound to its customer only"). Its
   slots are contact-time / channel preference / delivery habit / communication style; a
   legitimate value is `leave at back door, call 604-555-1212`. Running the PII leg over L4
   slot values would `policy_blocked` correct customer data. FR-10 asks only for **injection**
   hard-reject; S08's brief widened it to "injection/PII" and that widening is rejected.

**Decision — S01 lands the split** (first slice to touch the scanner) as two named resolvers in
ONE shared module imported by both the mock and Postgres twins (NFR-7):

| Field | `scan_injection` | `scan_pii` |
| --- | --- | --- |
| L7 `surface_form`, `canonical_form` | hard-reject | **not applied** — domain tokens are short and digit-shaped by nature |
| L7 `evidence`, `proposer_context` | hard-reject | **redact, do not reject** |
| L6 experience content | hard-reject | hard-reject (unchanged) |
| L4 slot values + evidence | hard-reject | **not applied** |

`evidence` / `proposer_context` are verbatim customer exchanges and will routinely contain a
phone or an email. Rejecting the whole entry over that throws away the governance evidence the
admin needs to decide. **Redact the matched span in place**, record that redaction happened,
and keep the entry.

Existing L6 behaviour must not change: `scan_agent_experience_content` keeps its current
semantics by composing the two new resolvers, and its existing tests stay green untouched.

## D3. L7 provenance and L6 source enums must be extended — nobody owned this

S25/S27 are told to emit `source = feedback_derived` **through** the governed propose actions.
That is currently impossible in two independent ways:

- `resolve_agent_experience_source` is framework-derived: it returns only `copilot_agent` for
  INTERNAL and deliberately ignores caller params. That is the ADR-0148 invariant and it stays
  — the fix is NOT a caller param.
- FR-1 pins L7 provenance to exactly `(admin_manual | conversation_confirmed)`, so an
  aggregator-mined lexicon proposal has no legal provenance value at all.

**Decision:**
- **S01** adds `feedback_derived` to the L7 provenance enum (three values) and makes the L7
  provenance resolver framework-derived from the execution context, never from a param.
- **S25** adds `feedback_derived` to the L6 source enum and the matching framework-derived
  branch in `resolve_agent_experience_source`, keyed on the **aggregator job's own execution
  context**. The existing INTERNAL → `copilot_agent` branch and its forged-param tests stay
  exactly as they are; S25 adds the matching forged-param test for the new branch.

Without this, feedback-derived proposals are indistinguishable from agent-proposed ones in
every queue — the one thing FR-32 exists to provide.

## D4. S09 — the ledger's gate and its write sites

1. **The gate is the eval axis, not the injection axis.** S09 says "gate on the same axes the
   injections are gated on — no injection, no row" AND "never on the record/replay path". Those
   are different axes: `eval_record.py` DOES call `render_injection` with a scenario memory
   preset, so the stated rule would write ledger rows during record and break the replay gate
   (NFR-4) inside S09's own acceptance. **Gate explicitly on "not an eval path"**, the way the
   existing eval-neutral emits are gated, and additionally skip when nothing was injected.
2. **Never put DB I/O in or around `render_injection`.** It is a pure, store-less function in
   the plugin package with three callers (`openrouter.py`, `copilot_turn.py`,
   `eval_record.py`). Writing from inside it is a layering violation and drags a DB dependency
   into the eval-record path. **Write from the callers**, with an explicit list of injected
   entry refs.
3. `entry_ref` is a **stable natural key, not a row id**: `binding_key + slot_name` for L4,
   entry id for L6/L7. The cross-channel merge path DELETEs and re-INSERTs L4 rows with new
   ids, so a row id would break S10's blast-radius join and S26's per-entry score.

## D5. S18 — the SLO is unmeetable as written and the store cannot hold the data

1. **`metric_event` is `(id, metric TEXT, flag BOOLEAN, created_at)` — no numeric column, so
   p50/p95 over it is arithmetically impossible.** Encoding a duration in the metric *name*, or
   reducing it to a boolean "was slow", satisfies the letter of the brief and is a defect.
   **S18 declares migration 0023** — a latency-sample table, or a nullable numeric column on
   `metric_event`; the implementer picks and documents the choice.
2. **The 150ms p95 total covers non-L5 pre-turn reads only.** L5's shipped budget is 800ms
   (`knowledge/driver.py DEFAULT_DEADLINE_MS = 800.0`), so any total including L5 can never
   meet 150ms — and FR-27 already scopes enforcement to "non-L5 pre-turn reads". L5 is still
   measured and tiled against its own 800ms budget, excluded from the SLO total.
3. **`merge` is a write, not a read.** Instrument it — it is on the pre-turn path and matters —
   but report it as its own tile, outside the read-SLO total. S19 already excludes it from
   parallelization for the same reason.

## D6. S05 — hit accounting must not be an in-turn UPDATE

A per-turn `UPDATE` of a counter column over a small hot set of confirmed entries is textbook
row-lock contention, and NFR-5 forbids adding anything to the reply path that can stall it.

**Decision: append-only + rollup, the shipped `honored_rate_aggregate` pattern.** Applications
emit an append-only hit event (migration 0026) or reuse S09's ledger rows as the evidence;
`hit_count` on the lexicon row is a **materialized column maintained by a scheduled rollup**,
never written in-turn. S20 and S26 read the materialized column.

## D7. S02 — edit semantics are PINNED (the either/or is withdrawn)

"In-place UPDATE with an old→new audit row" and "retire-old-then-write-new" are not
interchangeable: they diverge on entry id stability, `hit_count` continuity, and on whether
S09's `entry_ref`, S10's blast-radius join, and S26's per-entry health score survive an edit.
Shipping "either" guarantees one downstream join is wrong.

**Decision: in-place UPDATE. The entry id is stable across an edit.** An `old → new` audit row
records the change; `hit_count` continues (an edited entry is the same entry);
`UNIQUE(domain, surface_form)` is respected because the row is updated, not re-inserted.
Retire-then-write is reserved for the semantically different case where an admin means "that
mapping was wrong, kill it and start a new one".

## D8. S13 and S16 both claim one undefined column

S13 stores heuristic advisories on "the proposal row" via "an `advisory` JSONB field or sibling
— decide at implementation", declaring no migration. S16 later writes copilot annotations to "a
governed annotation field on the proposal row". Two slices, one undefined column, a lost-update
risk, and a requirement to render both side by side.

**Decision: S13 declares migration 0025** — ONE `annotations` JSONB column with two reserved
top-level keys, `heuristic` (S13's) and `copilot` (S16's). Each writer assigns its own whole key
and never touches the other's; the UI renders them as visually distinct blocks. S13's "no
migration" surface line is corrected.

`review_item` (S15) gets the same `annotations` column, because S16 annotates inbox items that
are not proposal rows (graduation, blast-radius, persona-review). Without it S16's scope
silently shrinks to the two proposal tables, contradicting FR-23.

## D9. S15 — item kinds

S20 emits a retirement kind S15's enum does not contain. **The `kind` enum is:
`l6_proposal, l7_proposal, graduation, blast_radius, persona_review, retirement_candidate`.**

## D10. S11 — the erase must actually erase, or the tripwire is theatre

`merge_provisional_memory` copies provisional slots from **every linked channel identity** onto
the verified key on the next verified turn, so a whole-binding erase is silently undone by the
customer's next SMS from a linked channel. US7 says "erases a customer's WHOLE memory binding";
today's S11 ships that hole as its tripwire's *happy path* — its acceptance **requires** a
post-erase merge to fire the alert, making the alert a permanent by-design false positive
rather than a signal.

**Decision: the erase clears the linked provisional bindings too** (all channel identities
linked to the binding), inside the same governed action, each with its own audit row. S11's
acceptance is corrected: a post-erase merge must **NOT** restore slots and must **NOT** fire the
alert; the alert fires only on a genuinely unexpected write.

## D11. S27 has no input — OWNER DECISION, default taken

S27 span-diffs "generated draft vs sent text". Verified against the merged qf code:
`draft_feedback` stores ONE text column (`draft_text` = the ORIGINAL generated draft, per
`GovernedSendModal.tsx` passing `originalBody`) plus a scalar `edit_distance_ratio`. **The SENT
text is persisted nowhere queryable** — `outbound_send` has no body column and no
draft-correlation id. S27's core algorithm has no second operand.

**Default taken (reversible, additive): S27 ships migration 0029 adding a nullable `sent_text`
to `draft_feedback`, written at governed-send time.** No backfill — mining sees only rows
created after it lands, and says so honestly on its surface. **The owner may instead cut S27
from 0.0.5.** Also note the edited-send stream is SMS-only by construction today.

## D12. S20 ↔ S09 — the retirement actuator is coupled to a garbage collector

S20 calls an entry zero-hit using ledger-derived usage; S09 prunes the ledger on a window sized
only "long enough for S10/S26 joins". Nothing constrains the two. If
`prune_window < zero_hit_window`, garbage collection silently manufactures retirement
candidates for actively-used entries — a memory-loss actuator driven by a GC artifact.

**Decision: both windows are named constants and `prune_window >= zero_hit_window` is asserted
in a test** that fails if either constant is edited to break the relation.

## D13. S25 / S20 — "job failure leaves queues clean"

Emitting through governed propose actions means each dispatch is its own transaction, so "clean
on failure" cannot mean transactional rollback without a compensating path nobody describes.

**Decision:** "clean" means **idempotent on retry via the watermark**, not transactional. A
propose that returns `policy_blocked` — a rep comment carrying a customer name or phone will do
this routinely — is **swallowed and counted** into a metric; it must never fail the job and
must never silently vanish. Both behaviours are stated in the slice and tested.

## D14. S22 — the knob panel — OWNER DECISION, default taken

S22 requires "a knob panel (read-only values + audited config change path)" and in the same
breath says "no in-UI mutation this iteration if config is file-based". A panel that renders
env-var names is not an audited change path, and NFR-3's knob clause leans on that path.

**Default taken: the panel ships honestly labelled read-only**, and 0.0.5 records plainly that
NFR-3's knob clause is satisfied by deploy-time config only (knob changes are git-auditable
because they are code/config commits), with no in-app enforcement this iteration. **The owner
may instead fund a real governed config action + audit row + config table.**

**Reconciliation — what "audited config change" means everywhere else in 0.0.5.** Several
slices use that phrase in a way that reads like an in-app action: S26 calls its hit-ranked
selection flip "an audited admin/config action", and S25/S06 put their thresholds and glossary
bound on the knob panel. Under this decision **all of them mean the same thing: a deploy-time
config commit.** The panel displays current values and never mutates them; the change lands as
a code/config commit whose audit trail is git history. Every slice that flips a knob must say
so plainly in its own text rather than implying a governed in-app action that does not exist —
an honest "changed by deploy" beats a UI that looks mutable and is not.

## D15. S09's ①-only carve-out is real but must be declared

NFR-1 allows the browser-E2E carve-out for pure-refactor/test-only slices; the README's audit
names exactly three (S12/S21/S23). S09 takes the carve-out while shipping a migration and new
runtime write sites. It is defensible — the ledger has no human surface until S10 — but the
audit that claims completeness must say so. **README's NFR-1 line adds S09, with the reason.**

## D16. Constants, not literals, from day one

S06 hard-codes "newest-20" and S25 hard-codes N=3/M=3, while S22 (much later) must render
"glossary N, bounds, windows" on the knob panel. **Introduce these as named module constants in
the slice that first uses them**, so S22 reads them instead of hunting magic numbers.

## D17b. `tools.ts` is a PARTIAL mirror, and its "drift test" does not detect drift

Found while implementing S01. The Python catalog has **23** tools; `packages/shared/src/tools.ts`
has **18**. Absent from the TypeScript side: `toee_delivery_promise`, `toee_integrations`,
`toee_job_queue`, `toee_metrics`, `toee_retention` — all shipped in 0.0.3/0.0.4.

The file calls itself the "v1 Domain Adapter Tool catalog", which would make a subset
legitimate — except that three post-v1 governed stores (`toee_agent_experience`,
`toee_feedback`, `toee_semantic_lexicon`) *were* added to it. So the stated purpose no longer
describes the contents, and there is no rule a reader can apply.

Worse, nothing protects it: `tools.test.ts` asserts "contains exactly the 18 v1 tool names"
against a **hardcoded list**. That test only fires when someone edits `tools.ts` without editing
the test. It cannot see the Python catalog at all, so it never had a chance to catch these five.
A hardcoded restatement of the thing under test is not a drift test.

**Decision for 0.0.5:** a slice that adds a **governed memory-layer store** mirrors it into
`tools.ts` — that is the convention the last three such stores actually followed, and S01
followed it. **0.0.5 does NOT backfill the five missing operations tools**: nothing in
TypeScript references them, so their absence is a typing/documentation gap rather than a
runtime defect, and quietly absorbing four earlier slices' debt into this iteration would hide
it rather than fix it. The real fix — a cross-language drift test that compares the two
catalogs and forces any exclusion to be explicit and justified — is filed as its own follow-up.

## D17. Catalog-sync (HOTSPOT-A) is serialized — one slice at a time

Nine files move together for any new tool/action: `tool_catalog.py`, `plugin.yaml`,
`schemas.py`, `profiles.py`, `plugin/__init__.py`, `mock/__init__.py`, `handlers/__init__.py`,
`tools.ts`, and their drift tests. **Exactly one catalog-touching slice is in flight at a
time**, in this order: **S01 → S02 → S15 → S11 → S10** (plus S16 if it adds a governed annotate
action). This is the real width limit of the plan.

## D18. Inherited debt from the qf merge — not silently "done"

The quality-feedback work merged into this branch carries two undischarged PAC items of its own
(a human browser DOM pass over ReviewBar / thumbs / send modal, and a simulator-driven PAC-1
subject; see `workspace/0.0.4/quality-feedback/PAC-CHECKLIST.md`). Folding qf into the 0.0.5
base makes them the 0.0.5 sign-off's problem. **They are listed explicitly in S29's walkthrough
as inherited items**, so they cannot ride along unnoticed as already-signed-off.

## D19. Fence-escaping memory values — a live injection surface, root-caused

Found by the S12 review. `plugin/hooks.py::_render_memory` interpolates raw customer-authored
slot values into the prompt with no escaping (`f"- {name}: {value}"`). A slot value that
contains the fence's own closing token — `</untrusted_customer_memory>` followed by a newline
and further text — **closes the fence early and places the remainder outside it**, which is
exactly the prompt-injection surface that function's own comment warns about. S12's
composition test does not catch it, because it only asserts that known content sits inside its
fence.

Today's injection patterns do not cover this: a fence-close token is not "ignore previous
instructions". It is a structural escape, not a semantic one.

**Decision — fix it at the root, in two places, both already owned:**

- **Write side (S01).** `scan_injection` treats **fence-delimiter tokens as an injection
  pattern class** and hard-rejects them. Because every layer's write path calls that one shared
  resolver, this covers L4 (S08), L6, and L7 in a single change rather than three.
- **Render side (S06).** S06 owns the prompt seam, so it escapes or strips fence-delimiter
  tokens at render time as defence in depth. A value that somehow reached the store before the
  write-side guard existed must still not be able to break the fence.
- **Test (S06).** S12's composition test gains the case it currently cannot catch: a slot value
  carrying a closing token renders with the fence structure intact. S12 ledgers the gap;
  **S06 closes it**.

Do not "fix" this by widening the composition test alone — a test that asserts a broken
renderer is still broken is not a fix.
