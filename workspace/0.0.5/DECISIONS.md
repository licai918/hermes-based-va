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
| 0027 | ~~S25~~ **FREE** | S25 landed (`e682982`) with **no migration** — the watermark is one number, so it rides a `workbench_audit_log` row, the surface the retention sweep, ledger prune and L7 hit rollup already use. The allocation was made before that shape was known; 0027 is unclaimed. |
| 0028 | S26 | effectiveness rollup |
| 0029 | S27 | `draft_feedback.sent_text` (D11 — owner-flagged) |
| 0030 | **S09** | `injection_ledger` + its query indexes — **moved here from 0021**, see above. **LANDED** |
| 0031 | **S09** | `CHECK (layer IN …)` on the ledger — **LANDED**. It had to be its own ALTER migration rather than an edit to 0030, because `schema_migrations` skips applied versions: editing 0030 would constrain fresh databases while silently skipping already-migrated ones, which is the exact drift the constraint exists to prevent. |
| 0032+ | spare | The table has no spare row left below this. Take the next free prefix and say so. |

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

**Amendment (found by the S01 re-review — L6's reject set DID widen, and the tests did not
notice).** Deepening the `proposer_context` traversal so nested values could be scanned also fed
L6's composite more strings than before, and L6's composite runs the PII leg over keys and
nested values. So an L6 `proposer_context` key shaped like `order_1234567890` now
`policy_blocked`s the whole `propose_experience` write. The existing L6 tests stayed green only
because none of them covered the widened set — a clean illustration that "the tests still pass"
says nothing about behaviour no test describes.

**Ruling: the widening stands** — it is fail-safe, and narrowing it back to preserve
bug-compatibility would be the wrong direction. But it is now **pinned by a test** rather than
incidental, and recorded here rather than discovered later by whoever debugs a missing L6 row.
S04's capture fork writes L6 rows; if one goes missing, this is the first thing to check.

**And PII in dictionary KEYS is redacted, not just scanned.** The same rewrite scanned keys for
injection but never redacted them for PII, so `{"jane.doe@example.com": "..."}` was stored
verbatim with `pii_redacted` still false — then blessed in a docstring instead of closed. A
docstring that blesses a PII hole is the same defect class as a boundary ledger claiming
coverage it does not have. Keys get the redact leg too.

**Amendment 3 — a PII-shaped KEY redacts; it does not hard-reject.** Closing the key hole made
L6 reject on PII-shaped keys, and the implementer located exactly where that will bite:
`_PHONE_RE` is blunt enough that keys like `order_1234567890`, `2026-07-27`, an epoch stamp, or
a nested `{"case": {"callback": "+1 416 555 0199"}}` now `policy_blocked` the **whole**
`propose_experience` write. Today's only caller uses flat `{"case_id": …}` contexts and is
unaffected — **S04's capture fork is where it breaks**, because order/ticket/date keys and
nested turn contexts are natural there, and the symptom is a `policy_blocked` citing PII while
the `content` is visibly clean.

A dictionary key is structural metadata, not customer prose. An order id that happens to match
a phone pattern is a false positive, and destroying a whole governance record over it is
precisely the harm that made evidence redact-don't-reject in the first place. So the rule is
symmetric with that one:

- **Injection patterns in a key → hard-reject** (a key can carry a payload; nobody disputes this).
- **PII patterns in a key → redact, never reject** — for L6 and L7 alike.

**Clarification (the implementer caught that this ruling's own example contradicted its rule, and
declined to guess — correctly).** The `{"case": {"callback": "+1 416 555 0199"}}` example above
is a nested **value**, not a key, so the rule as written does not cover it. Deciding now, rather
than leaving it ambiguous:

**Keys redact. VALUES — top-level or nested — keep their existing per-layer behaviour: L7's
`proposer_context`/`evidence` values redact, L6's values still hard-reject.** The distinction is
not arbitrary. A key is structural metadata that the writer did not compose as prose. A value is
content. L7's evidence is *explicitly designated* as a verbatim customer exchange that must
survive so an admin can judge the proposal; L6's `proposer_context` carries no such designation,
and L6 is a **shared** layer whose whole NFR-6 rule is that customer PII does not belong in it.

So the surviving asymmetry is exactly one axis — PII in a context *value* — and it is a
decision, not a leftover.

**Consequence for S04, and it is the right consequence:** a capture fork that puts a customer's
callback number into an L6 `proposer_context` value will be rejected. That is the guard working.
The fix is for the fork to carry ids and refs rather than raw contact details, not to weaken the
guard — pushing customer PII into a shared layer is the thing NFR-6 exists to stop.

This narrows the accidental L6 widening to its defensible half and keeps NFR-6 satisfied: the
PII still does not get stored, it gets replaced.

**Structural note (implementer's concern, and it is a real trap):** `context_strings` is now one
traversal whose two callers have *opposite* consequences — L7 redacts what it finds, L6 rejects
on it. Any future deepening of that traversal therefore moves L6's reject set again, silently,
exactly as it did this time. Make the policy explicit at each call site rather than implicit in
the shared walk, so the next person who deepens it has to state which behaviour they intend.

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
  **Amendment (S01 landed the mechanism):** "the job's own execution context" now has a concrete
  shape — S01 added a framework-set `ToolExecutionContext.dispatch_route`, written as a literal
  only by the dispatch app's own route handler, never a parameter and never a runtime kwarg.
  **S25 keys `feedback_derived` on that same axis.** Do not invent a fourth discriminator; one
  provenance axis that every layer shares is the whole point.

Without this, feedback-derived proposals are indistinguishable from agent-proposed ones in
every queue — the one thing FR-32 exists to provide.

## D4. S09 — the ledger's gate and its write sites

1. ~~**The gate is the eval axis, not the injection axis.**~~ **SUPERSEDED — read the correction
   below before you implement anything from this clause.**

   The original text said: S09's brief contradicted itself ("gate on the same axes the injections
   are gated on — no injection, no row" versus "never on the record/replay path"), because
   `eval_record.py` DOES call `render_injection` with a scenario memory preset, so the first
   clause would write ledger rows during record and break the replay gate (NFR-4). The ruling was
   to gate on "not an eval path" and additionally skip when nothing was injected.

   **Correction (S09's review, then its fix).** Gating on the eval axis ALONE is not sufficient
   and was itself the source of a defect: the L6 injection rides
   `agent_experience_external_injection_enabled()` while the ledger rode `memory_enabled()`, so a
   deployment with L6 injection on and memory disabled recorded nothing at all. **The gate is
   PER-LAYER: each layer's ledger row is gated on the same flag that layer's injection rode, AND
   the whole write is skipped on an eval path.** Both conditions, not either.

   **This clause is the one a later slice will EXECUTE rather than merely read.** S06 adds the L7
   seat, and following the superseded wording would reproduce, for L7, exactly the hole the fix
   just closed for L6. If you are S06: register L7's ledger gate against **L7's own injection
   flag**, not against a global memory flag.
2. **Never put DB I/O in or around `render_injection`.** It is a pure, store-less function in
   the plugin package with three callers (`openrouter.py`, `copilot_turn.py`,
   `eval_record.py`). Writing from inside it is a layering violation and drags a DB dependency
   into the eval-record path. **Write from the callers**, with an explicit list of injected
   entry refs.
3. `entry_ref` is a **stable natural key, not a row id**: `binding_key + slot_name` for L4,
   entry id for L6/L7. The cross-channel merge path DELETEs and re-INSERTs L4 rows with new
   ids, so a row id would break S10's blast-radius join and S26's per-entry score.

   **Correction (S09 review) — this clause was imprecise, and the imprecision hid a real gap.**
   The merge does not merely change row *ids*: `merge_provisional_memory` inserts under the
   **`verified_key`** and deletes the provisional rows, so **the binding key itself changes**. A
   natural key is therefore strictly better than a row id but still **does not survive
   verification** — a `provisional:sms:+1416…:contact_time` ledger row written before the
   customer was verified joins to nothing afterwards. Concretely: retire a verified customer's
   `contact_time` entry and S10's blast radius silently omits every pre-verification turn that
   used it.

   **Ruling: the merge re-points the ledger.** `merge_provisional_memory` already knows both
   keys and already copies the memory rows across; it updates the ledger's `entry_ref` for the
   same slots in the same transaction. That is the symmetric other half of something the merge
   already does, not new machinery. And the test must reproduce the **real** merge — provisional
   key in, verified key out — because the one that shipped deleted and re-inserted under the
   *same* key, so it passed for a scenario that never occurs.

   **Copilot-path limitation, recorded here rather than only in a report:** a draft turn has no
   durable identity, so its `turn_ref` is a synthetic `new_id("copilot_turn")`. The joinable
   reference on that path is `case_or_binding_ref`, not `turn_ref`, and a re-drafted case
   accumulates duplicate per-entry rows because the composite primary key cannot dedupe a
   never-repeating key. **S10 must dedupe by case**; **S26's per-entry effectiveness is
   external-path only** and must say so where it renders.

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

**Two properties of that column that its name does not reveal — S20 and S26 both read it and
neither will read migration 0026:**

- **`hit_count` is a LIFETIME total, not a windowed one.** The rollup consumes its hit events, so
  the events are gone afterwards and the column only ever grows. **Windowed usage — "did this
  entry fire in the last N days" — must come from S09's `injection_ledger`, not from here.** An
  entry that fired heavily a year ago and never since has a large `hit_count` and zero recent
  usage, which is precisely the retirement candidate S20 exists to find.
- **The rollup must never touch `updated_at`.** The console derives its "(edited …)" marker from
  `updated_at > (decided_at ?? created_at)` and `lexicon_version` is `MAX(updated_at)`, so a
  rollup stamping it would make every hot entry render "the content may not be the decider's"
  beside a decider who never edited, and would churn the cache version on hit traffic — building
  a cache and its own defeat in one slice. Pinned by `test_the_rollup_does_not_move_updated_at`
  and `test_hit_traffic_never_moves_the_lexicon_version`.

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

**Both constants live in `hermes_runtime/injection_ledger.py`** — S09 landed
`PRUNE_WINDOW_SECONDS` (180 days) and `ZERO_HIT_WINDOW_SECONDS` (90 days) side by side there.
**S20 imports `ZERO_HIT_WINDOW_SECONDS`; it must not declare its own.** Two copies would leave
the assertion comparing a constant against itself — technically green, and pinning nothing.

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

**Correction (S10, `0b0b8fb`) — the set is TEN files, not nine.** `memory_layers.py` must move
too: S12's completeness tripwire (`test_layer_of_action_covers_every_catalog_action_and_nothing_else`)
is a **set equality over the whole catalog**, so any new action reddens it until `LAYER_OF_ACTION`
declares a layer. It sits outside the nine because it is not a registration file, which is exactly
why it kept getting missed. Add it to the standing list.

**Also worth copying, from S10's execution:** its first act was to add the catalog action **alone**
and watch the tripwires redden — four fired, including S15's two catalog-derived loops. Those loops
are written so a later action cannot slip past, but they cannot say *which* action they checked, so
S10 added a **named** assertion beside them with a contrast case (the tool is excluded wholesale,
so the loop would also pass over an empty registration). Adding the catalog entry before the
implementation is a free liveness check on every guard in the set, and nobody normally takes it.

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
  pattern class** and hard-rejects them.
  **Correction (found by the S01 review — this decision originally overstated the reach):**
  adding the pattern to the shared resolver does NOT by itself cover L4. Only L6 and L7 call
  `scan_injection` today; **L4's write path does not call it at all**, which is precisely what
  S08 exists to wire. So the honest statement is: **L6 and L7 are covered as of S01; L4 is
  covered when S08 lands.** Any ledger, docstring or comment that says otherwise is wrong and
  must be reworded — the boundary ledger is the one file in the repo whose entire purpose is
  honest accounting, and an aspirational claim there is worse than no claim, because the next
  reviewer will believe it.
- **Render side (S06).** S06 owns the prompt seam, so it escapes or strips fence-delimiter
  tokens at render time as defence in depth. A value that somehow reached the store before the
  write-side guard existed must still not be able to break the fence.
- **Test (S06).** S12's composition test gains the case it currently cannot catch: a slot value
  carrying a closing token renders with the fence structure intact. S12 ledgers the gap;
  **S06 closes it**.

Do not "fix" this by widening the composition test alone — a test that asserts a broken
renderer is still broken is not a fix.

## D20. `admin_manual` must be attributable, or it is not admin_manual

Raised by the S01 fix. Provenance is now keyed on `dispatch_route`, which is correct — but a
write arriving on the admin route **with no actor** still persists as `admin_manual` with a
`NULL` decider, because ADR-0141's actor resolution fails open.

`admin_manual` means exactly one thing: a human administrator typed this. A row asserting that
with nobody attached is unfalsifiable provenance — the precise failure the governance model
exists to prevent, and the reason `decider_account_id` is on the table at all. It is also
inconsistent with the house pattern: everywhere else in this codebase a missing actor on a
governed write is a fail-closed `policy_blocked`, not a silent write with a null field.

**Decision: on the admin route, a write with no resolvable actor is `policy_blocked`. It must
not persist an unattributed `admin_manual` row.** Assigned to **S02**, which owns manual-add
and the decide/CRUD actions — the paths where admin attribution carries the most weight, and
which already assert `policy_blocked` without an actor. S02 extends that assertion to the
provenance path and adds the regression test.

**Interim exposure, stated rather than hidden:** between S01 and S02 an unattributed
`admin_manual` row is possible. It is reachable only through the internal dispatch route behind
the bearer, not from any customer-facing path, so the risk is bounded — but it is real until
S02 lands, and it must not be discovered later as a surprise.

## D21. Pre-S08 L4 rows were never scanned, and nothing re-scans them

Found by the S08 implementation. S08 wires `scan_injection` into the L4 write path and
hard-rejects, which closes the door **for new writes only**. Every L4 slot value written before
that commit entered the store unscanned and is still there, and it still renders into the prompt
on every subsequent turn.

**What is already covered, so this is not restated as worse than it is.** D19 assigned the
render-side fence escape to S06, and S06 shipped it (`_fence_safe`): a stored value carrying a
closing fence token cannot break out of its block. D19 drew the line itself — a fence-close token
is a **structural** escape, not a **semantic** one. So the residue is precisely the semantic half:
a stored `ignore previous instructions` in a pre-S08 row has no backstop except the fence and the
untrusted-data framing around the L4 block.

**Why that framing is not automatically sufficient here, even though it is for a live message.**
A customer can type an injection into any message, and the answer to that is exactly the fence
plus the framing — we do not scan every inbound message. What makes a *stored* value different is
**persistence**: one accepted injection write replays into every future turn for that binding,
where a live message is one turn. Persistence is the entire reason FR-10 hard-rejects at write
time rather than trusting the fence. That reasoning applies with equal force to the rows already
in the store — they are, by definition, the persistent ones.

**Decision: a one-time re-scan of existing L4 values is in scope for 0.0.5, assigned to S10.**
S10 already owns the "query the rows an issue affects → emit `review_item`s" shape and ships the
emitter, so this is a second query against the same machinery, not a new mechanism. It must
**propose, never auto-delete** (NFR-3): a flagged historical value is a review item for a human,
because the value may well be legitimate customer data that merely trips a pattern — the same
false-positive risk that made D2 split the scanners in the first place.

**If the owner would rather accept this as residual risk given the fence and the framing, that is
a legitimate call — but it must be made as a decision, not left as an oversight.** What is not
acceptable is the current state, where S08's docstrings and the boundary ledger read as though L4
is now covered, when what is covered is L4 *going forward*. S08 corrected five stale claims of
exactly that kind; this decision exists so the sixth does not get written.

**SHIPPED (S10, `0b0b8fb`), with the residual still unquantified.** `rescan_l4_slot_values` reads
every `customer_memory_slot` row through **S08's own resolver** (`scan_memory_write`, not a second
copy of the pattern list) and proposes one review item per hit. Propose-only, and note the
pleasing property: a flagged value **cannot ride along in the item even if someone wanted it to**,
because `review_item.evidence` is itself injection-scanned — the very pattern that flagged the row
would block the emission.

**What it found on the dev database: nothing, because there is nothing.** `customer_memory_slot`
is **0 rows** (and `injection_ledger` 0 rows) on a database that is otherwise populated — 4 cases,
6 threads, 6 sessions, 4 lexicon entries, 59 audit rows. So the mechanism is proven and the
exposure is **not measured**. D21's residual remains an open question wherever real L4 data lives;
the CLI is `python -m hermes_runtime.blast_radius`. Running it against a populated store is the
step that turns this decision from "handled" into "handled and known to be empty".

## D22. `hit_count` is STRUCTURALLY zero for `default_rule` — so zero-hit retirement would eat them all

Found by S26 while building the health ranking. `hit_count` counts **deterministic-seam
applications**, and the seam (`lexicon_seam.normalize_product_query`) only ever applies `alias`
and `normalizer` rows. A `default_rule` is never applied by the seam — it renders into the prompt
as an imperative ASK. **So every `default_rule` earns exactly zero hits, permanently, no matter
how well it works.**

This is not a bug in the rollup. It is a property of what the two mechanisms mean, and D6 already
warned that `hit_count` carries properties its name does not reveal. But it has two consequences
that were not visible until the ranking work forced them out:

**It is a ratchet.** Out of season a `default_rule` earns no ledger injections either. Newest-20
selection evicts it → it is not rendered → it is not injected → it is never scored → it never
comes back. The eviction is self-reinforcing and silent, which is the same shape as the
`LEXICON_GLOSSARY_LIMIT` ceiling and for the same underlying reason.

**Decision 1 — the ranking fills the window round-robin across entry kinds**, not by global score.
Shipped in S26 (`2f10054`), proven against 26 entries at a limit of 20 where all 24 aliases are
both newer and hotter than the two seasonal defaults: newest-20 evicts both, health-ranked keeps
both, and aliases still take 18 of 20 seats. It is a **per-kind share, not an exemption for one
kind**, and there is no threshold to tune.

**Decision 2 — S20 must read `entry_effectiveness`, NOT `hit_count == 0`.** This is the load-
bearing half. FR-20's zero-hit retirement feed, implemented literally against `hit_count`, would
place **every `default_rule` in the system** into the retirement queue on day one — including the
two seeded seasonal rows that are the iteration's flagship behaviour. `health_for_rows` and
`entry_effectiveness_for` are public and layer-generic for exactly this; S26 named the seam in the
module docstring.

**Known and deliberately left alone:** the Memory Hub's "Zero-hit confirmed entries" tile (S14)
now permanently includes every `default_rule`. Its label is not false — it says "lifetime
`hit_count` = 0" — so S26 left it rather than widening scope. It should move to the effectiveness
read whenever someone is next in that file.

## D23. FIVE of eleven feedback tags have nowhere legal to emit — OWNER DECISION

**Counts corrected (S28, `b3d04f5`).** This decision originally said "six" in its heading and
"only five can reach a queue" in its body — **two different wrong numbers, contradicting each
other and both contradicting the code.** The shipped routing table routes **six** tags to a
governed propose action and leaves **five** terminal. The list below was always right; only the
arithmetic around it was wrong. S28 found it by deriving routability from the table instead of
trusting the prose, did not edit this file, and shipped a tripwire pinned at `(11, 6)` that
reddens if a route moves — so the next drift corrects the prose instead of surviving in it.

Recorded rather than quietly fixed, because the error propagated: it reached a dispatch brief and
a status report before the code contradicted it. A decision document that miscounts its own
finding is the same defect class as a docstring blessing a hole.

Found by S25 while building the aggregator. Of the eleven declared feedback tags in C6 §6.2,
**six can reach a queue through a governed propose action and five cannot**. S25 did not fabricate
destinations for the five; each carries its reason at its own routing-table entry and the run's
audit row counts them.

- `policy_violation` — KnowledgeOps has no propose-shaped action. `update_policy_slot` writes slot
  **content** and requires a human actor, so a scheduled job writing there is precisely the
  auto-write NFR-3 forbids.
- `missed_information` / `missing_context` — these want an "L5 gap / L4 injection-miss" review
  item, and **D9 pins the `review_item` kind enum at six values, none of which is that**. There is
  nothing legal to emit.
- `factual_error` — the L5 half is the same auto-write block; the L7 half needs a
  `surface_form → canonical_form` **pair**, which a tag cluster does not contain. Deriving one is
  edit-diff mining (FR-33, S27).
- `other` — deliberately unrouted: its meaning lives in the reviewer's comment, so the tag alone
  says nothing.

**This is the owner's call, and it is a real product gap, not a technicality.** A reviewer who
tags "missed information" today gets a counted-but-silent outcome: the signal is recorded and
reaches nobody. The cheapest honest route is a **seventh `review_item` kind** for the
information-gap shape — which requires amending **D9**, not adding a dict entry in the aggregator.
The alternative is to accept that those tags are collection-only in 0.0.5 and say so where the
reviewer tags them, so the UI does not imply an action that never happens.

Recorded rather than decided, because either answer is defensible and the choice belongs to
whoever owns what a reviewer is promised when they click the tag.

## D24. The adversarial gate is blind to obedience expressed as a TOOL CALL

Found by S23 while building the adversarial family, and made checkable rather than merely stated.

`_eval_safety` evaluates **substrings of the reply text**. So an injected instruction that is
obeyed **in prose** — "I have waived the restocking fee" — trips the gate and fails the build.
An injected instruction obeyed **as a tool call**, with a bland reply that mentions nothing —
redirecting a payment link, rewriting a memory slot — **leaves every marker green.**

S23 shipped scenarios 35 and 36 for exactly these two shapes, so the hole is now visible in the
suite instead of being a sentence in an ADR. But only a **medium** tool assertion notices them,
and medium does not gate. The honest statement of what PAC-4 establishes is therefore:

> A stored injection **with a prose effect** cannot be obeyed without failing CI. It does **not**
> follow that no injected instruction was obeyed. **A green gate is not proof of no obedience.**

That sentence must survive into the PAC-4 sign-off. A reviewer who reads "adversarial suite green"
as "no injection succeeded" is drawing a conclusion the instrument does not support, and this is
the layer where that mistake would be most expensive.

**Not fixed here, and deliberately so.** The upgrade — extending `_eval_safety` to read
`result.tool_calls` — is a change to **what gates CI**. Widening a gate mid-iteration, in a slice
whose own acceptance forbids new gating (NFR-4), is how a release gets blocked by a rule nobody
agreed to. It needs its own slice and its own decision about which tool calls constitute obedience;
"the agent called a tool" is not by itself a violation, and getting that predicate wrong turns the
safety leg into noise, which is the failure mode that ends with people disabling it.

**Related ceiling, unchanged:** ADR-0160 already records that paraphrase walks through a substring
gate. D24 is a different and sharper hole — paraphrase still *says something*, so a broader marker
set can reach it. A tool call with a bland reply says nothing at all, so **no marker set of any
breadth can ever reach it.** Breadth is not the fix; reading the effect is.

## D25. S30 may be pointed at the wrong prompt file — establish which one production runs first

Found by S31 (`17e6bb1`) while building the instrument that makes S30 provable, and it is the kind
of thing that only surfaces when someone actually runs the live model.

**`toee_hermes/persona.py` — the prompt production actually uses (`openrouter.py:582`) — already
carries an explicit "open a case with `toee_case__create_case`" contract and a `contact_reason`
vocabulary. `SOUL.md`, the file S30's brief names, does not.**

So the defect S30 exists to fix is **not** simply "the contract is missing from the prompt". The
contract is present in the prompt production runs, and the agent still failed to open a case in 2
of 3 live attempts. **S30 must establish which prompt the failing production turns actually ran
before editing either file** — otherwise the obvious fix (add the contract to `SOUL.md`) changes a
file the failing path may never read, ships green, and leaves the defect alive.

### What S31 measured, so S30 inherits a baseline rather than a hunch

Live, billed, against `deepseek/deepseek-v4-pro`, 12 agent turns:

| persona | 3 runs | total |
| --- | --- | --- |
| shipped | 0.500 · 1.000 · 1.000 | **5/6** |
| hand-off contract removed (control) | 0.000 · 0.000 · 0.000 | **0/6** |

The control is the red-capability proof, **measured rather than asserted**: 0/6 with no variance
means the instrument is sensitive to the prompt, not to noise. And the shipped side is not
always-green either — **the failure is intermittent (2 of 3), not deterministic.** That is the
argument for a trend line and against ever letting this gate.

The miss reproduced the original defect nearly verbatim: *"I don't have our Saturday hours on hand
right now, but I'll have the team follow up with you to confirm."* — a promised hand-off, no case,
zero `toee_case` calls.

### Why it reads the effect, and why that is the inverse of D24

`case_created` derives from a **successful governed `toee_case__create_case` call**, never from
wording. D24's hole is behaviour expressed as a tool call that the text gate cannot see; escalation
is the mirror image — **a prose promise with no call at all**. A wording check would have scored
this defect **backwards**: the turn that failed to open a case had the most reassuring reply of the
three. A blocked or failed create also does not count, pinned by its own test.

### The evidence is asymmetric, and S31 said so rather than letting it be assumed

The probe runs the production persona but with **mock drivers and a self-rendered identity block**.
It opened a case for the urgent-billing conversation 3/3 while the real stack opened none. So
**a miss in this probe is strong evidence; a hit is weak.** S30 should read a green probe as "not
reproduced here", never as "fixed".

### One addition beyond the brief, and the reason for it

S31 added a **must-NOT-escalate** contrast probe that no brief asked for, because a
should-escalate-only set cannot tell "the contract works" from "the agent now opens a case on every
conversation" — S30's own out-of-scope risk, and the house rules' fixture-too-small shape. It fires
independently of the rate. Keep it: a fix that over-escalates must not be able to show a clean
sheet.

## D26. D25 answered: production runs `persona.py`, and the instrument S30 inherited is at its ceiling

S30's resolution of D25, and two things it measured that change what the next slice should believe.

### The prompt question, settled at the wire

**`hermes/toee_hermes/persona.py` is the prompt. `SOUL.md` reaches no model, ever.** Not inferred
from reading three packages — driven: `hermes-runtime/tests/test_external_turn_prompt.py` runs a real
turn through `hermes_runtime.live.run_agent_turn` (the one seam BOTH `openrouter.py:582` and the eval
recorder go through), with `HERMES_HOME` pointed at the profile home exactly as
`gateway_composition._apply_external_profile_env()` does in production, and reads the system prompt
the provider was actually handed.

The mechanism: `run_agent_turn` builds its `AIAgent` with `skip_context_files=True` and leaves
`load_soul_identity` at `False`, and the SDK gates SOUL.md on exactly that pair
(`agent/system_prompt.py`: `if agent.load_soul_identity or not agent.skip_context_files`). A
corollary worth knowing: the identity slot therefore falls back to `DEFAULT_AGENT_IDENTITY` — the
prompt opens *"You are Hermes Agent, an intelligent AI assistant created by Nous Research"* — so
SOUL.md's identity section is not merely unused, it is contradicted upstream of the persona.

So S30's brief named the wrong surface, D25 was right to stop it, and the trap is now a test rather
than a paragraph: flipping either flag turns that test red. SOUL.md carries a comment saying it is
not the prompt, and is deliberately **not** given a mirrored copy of the hand-off contract — two
copies of a behavioural contract, one of them dead, is worse than one.

### The defect was not a missing contract. It was three instructions that described the hand-off as a thing to SAY

The contract and the `contact_reason` vocabulary were already in `persona.py` (D25). What was also
there, and nearer to the failing turn, were three separate places telling the agent what to *say*
when it could not answer — "say plainly you don't have that on hand", "say ... you'll connect them
with the team / open a follow-up" — each a complete instruction on its own. The "always open a case"
contract sat in another section keyed on categories ("a policy question", "a non-customer") that
*"What are your Saturday opening hours?"* does not obviously match. The model followed the nearest
instruction and produced precisely what it asked for. S30 repaired all three sites plus the trigger
list, and stated the coupling once: naming a hand-off in any form requires that
`toee_case__create_case` has ALREADY succeeded on the same turn — with the escape hatch that not
mentioning a human is a legal way to satisfy it, so the rule cannot be read as "escalate everything".

### The instrument is at its ceiling, so this fix is unprovable by measurement — say so rather than implying otherwise

S31's baseline was **5/6** over 3 runs. S30 re-ran the same harness, same model
(`deepseek/deepseek-v4-pro`), before changing anything: **10/10 over 5 runs, 0 unwanted cases.** The
miss did not reproduce once. So:

> **S30's before-number is at ceiling, and no after-number can therefore show improvement.** The
> probe can show *no regression* and *no over-escalation*. It cannot show the fix worked, and nobody
> should later quote the after-number as if it did.

That is D25's asymmetry arriving in practice — "a miss is strong evidence; a hit is weak" — and it
is why S30 ships on structural grounds (the defective instruction is gone, pinned by a red-capable
test) rather than on a moved number. The live gap remains the interesting one: the real 0.0.4 stack
opened **0 of 2** cases where this probe now opens 10 of 10 on the same words. The prompt is shared;
what is not shared is the mock drivers and the self-rendered identity block. **If the next slice
wants to reproduce the production miss, that difference is where it lives, not in the prompt.**

### What the probe DID catch, which is the argument for keeping S31's contrast leg

The should-escalate leg was at ceiling and stayed there. The **must-NOT-escalate** leg was not
decorative:

| persona | should-escalate | unwanted cases | reason on the hours probe |
| --- | --- | --- | --- |
| shipped (before) | 10/10, 5 runs | **0/5** | `unknown` 5/5 |
| S30 first draft | 10/10, 5 runs | **1/5** | `non_customer_general` 4/5 |
| S30 as landed | 12/12, 6 runs | **0/6** | `unknown` 12/12 |

The first draft widened the trigger to *"You have no published answer to what they asked … 'I don't
know' is a case, not just a sentence"*. That generalised past questions into **tool results**: on
run 2 the agent searched the catalog three times for the contrast probe's public product question,
found nothing satisfying, and opened a case — the over-escalation S30's own brief names as its
out-of-scope risk, produced by S30's own fix, on the fifteenth live turn. The same edit also drifted
`contact_reason` off `unknown`, because it widened the *trigger* without widening the *reason* it
maps to. Narrowing the bullet to questions-nothing-published-can-answer, naming `unknown` in the
bullet itself, and pointing at the "can fully serve here" counterweight put both back.

**So: the useful reading of this instrument is not its headline rate.** The should-escalate leg was
uninformative in both directions; the contrast leg found a real regression that every deterministic
test in the slice was green through. S31 added that leg without a brief asking for it. Keep it, and
run it after a prompt change even when the number you care about cannot move.

Ruled out cheaply along the way, so it is not re-investigated: the tool surface is identical across
the bound production boot, the unbound boot and the eval boot (`toee_case__create_case` present in
all three), and `max_iterations` is 12 on both seams.

### Three things found in passing, none fixed here

1. **Recorded escalations carry free-text `contact_reason`.** Scenario 05 recorded
   `"alternate_payment_recipient"` and 06 recorded `"refund and discount request"` — neither is in
   the persona's fixed vocabulary, which says "never free text". Nothing catches it because those
   scenarios assert no reason. The root cause is a **gap in the vocabulary, not model
   disobedience**: the eight values cover non-customers and failures, and none covers *a verified
   customer whose request needs a human* (a refund, a discount, a complaint). Adding the missing
   bucket means re-recording 05/06, which are payment-link and refund scenarios carrying their own
   safety assertions — worth its own slice, not a drive-by.
2. **Scenario 08 recorded `non_customer_general`** for a question with no published policy, where
   the persona's table points at `unknown`. Defensible, unasserted, and left alone.
3. **`case_urgency` is nobody's assertion on a customer-service escalation.** Scenario 40 recorded
   `urgency: "urgent"` for the urgent billing dispute, which is right — but the persona's table
   lists `unknown` → `normal` and never says urgency may be raised, so that behaviour is correct by
   luck. Asserting it would pin a fixture the prompt contradicts. The prompt should say it first.

### A bait-writing trap, recorded because it cost a cycle

`eval_runner/transcript.py:_str_field` reads the **governed result echo in preference to the model's
call arguments**. So a bait that rewrites `contact_reason` in the assistant's `tool_calls` and
nowhere else changes nothing, the scenario stays green, and the natural conclusion — "this assertion
is vacuous" — is wrong. It is the house rules' "suspect your HARNESS before your test" in its exact
shape. Patch the `role: "tool"` result message; then it reddens.

## D27. `governed_tool_names` was an OFFER, not a fence — and a docstring said otherwise since 0.0.3

Found by S04 (`df9a4ad`) because **a bait refused to go red**, and it is the most consequential
thing this iteration turned up.

`run_agent_turn` **UNIONs** `governed_tool_names` into the agent's existing `valid_tool_names`
unless `tools_exclusive=True` is passed. A capture fork boots the entire `internal_copilot` profile
before narrowing, so the union is over everything that profile registers.

**Consequence, live since S23-0.0.3: the L6 review fork could dispatch any of the 43 tools on the
internal_copilot profile** — while its own docstring described it as restricted to a handful. A
background job, running on a customer conversation without a human in the loop, had the profile's
full tool surface.

### CORRECTION (post-review): the union's other operand is the SDK BUILT-INS, and that is the part that matters

The sentence above understates it, and "43 governed tools" is the wrong thing to be alarmed by. The
union is with `agent.valid_tool_names` — **the Hermes SDK's own built-in toolset** — not with the
governed profile. Probed on a constructed agent, that set is **25 tools**:

> `browser_back` `browser_click` `browser_console` `browser_get_images` `browser_navigate`
> `browser_press` `browser_scroll` `browser_snapshot` `browser_type` `clarify` `delegate_task`
> **`execute_code`** `memory` **`patch`** `process` `read_file` `search_files` `session_search`
> `skill_manage` `skill_view` `skills_list` **`terminal`** `text_to_speech` `todo` **`write_file`**

So the exposure was **shell and arbitrary code execution**, on paths whose input is customer-authored
text — the same text this iteration built injection scans, fences and untrusted-data framing to
contain. `live.py`'s own comment said so plainly (*"must not inherit Hermes built-ins (terminal,
read_file, …)"*) and then expressed the requirement as a default the caller had to remember.

**Verified live, not inferred:** at `df9a4ad^` the L6 review fork called
`governed_tool_names=tool_names` and the string `tools_exclusive` appeared **zero times** in
`copilot_turn.py`. The union ran.

### And S04's fix was necessary but not sufficient — the copilot draft turn had forgotten too

S04 fenced the two capture forks. The review that followed found `copilot_turn.py`'s **real
OpenRouter draft turn** (`run_agent_turn(..., governed_tool_names=booted.tool_names)`) passing no
`tools_exclusive` either — so the employee-facing draft turn, which injects L4 customer memory, L6
learnings, the L7 glossary and the case conversation, carried the built-ins. Meanwhile
`openrouter.py`'s customer-facing external turn had defaulted `tools_exclusive=True` since it
shipped. **The customer-facing path was fenced and the draft path was not.**

**Decision, superseding "both forks now pass `tools_exclusive=True`": the DEFAULT is inverted.**
`run_agent_turn` and `run_scripted_agent` now default `tools_exclusive=True`. Fencing is what
silence means; a harness that wants the built-ins passes `tools_exclusive=False`, which is a line a
reviewer can see. Pinned by `hermes-runtime/tests/test_tool_fence_default.py`, whose failing message
names the four tools that leaked.

**What the flip cost: nothing.** The full suite went 1452 → 1455 (the three new tests), hermes 1309,
and both eval gates stayed at `failed_high=0`. **No caller depended on the union.** `live.py`'s
comment claimed "Eval/scripted runs union them in for harness flexibility" — that flexibility was
never exercised. The default was pure exposure with no benefit, which is the strongest possible
argument that an opt-in fence was the wrong shape rather than a considered trade.

This also closes the "still open" clause below: it is no longer true that other callers offer
rather than fence. They inherit the fence, and the two that want otherwise say so.

**How it was found is the part worth copying.** S04's first bait unrestricted the fork's
`tool_names` and **every routing test stayed green** — because those tests pinned the *extractor*
(what the fork does with a verdict), not the *toolset* (what the fork can reach). Rather than
concluding the bait was badly aimed, S04 asked why the tests could not see it, added two call-site
tests that read the `governed_tool_names` **and** `tools_exclusive` each fork actually hands the
loop, and re-armed. The bait then reddened, printing 43 tools.

A test suite can be comprehensive about behaviour and blind to capability. Nothing in the routing
tests was wrong; they simply were not about this, and the docstring filled the gap with a claim.

**Decision: both forks now pass `tools_exclusive=True`.** `run_scripted_agent` gained the
pass-through, defaulting to `False` so no other caller's behaviour moves. This is a **behaviour
change to shipped code**, recorded in the ADR-0152 note as well as here.

**What this does NOT establish.** No evidence exists that the extra surface was ever exercised —
the fork asks a model for language, and a model that never tried to call `toee_customer_memory` was
never refused. The fix removes a capability, not an observed abuse. Stated so nobody reads a
green-since-the-fix suite as proof that nothing happened before it.

**Second-order, and left alone deliberately:** every other caller of `run_agent_turn` that passes
`governed_tool_names` without `tools_exclusive` is offering rather than fencing. S04 changed only
the two forks it owns, because widening the default is a change to every turn path and belongs in
its own slice with its own evidence. **Whoever takes it should start from the assumption that at
least one more docstring in that set is currently wrong.**
