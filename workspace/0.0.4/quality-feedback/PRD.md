# PRD 0.0.4 / quality-feedback — human scoring of AI output, fed back under governance

- **Status:** drafted 2026-07-21 from the grilled design
  ([design spec](../../../docs/superpowers/specs/2026-07-21-manual-scoring-feedback-design.md)),
  reconciled against 0.0.3 and then rebased onto post-0.0.3 `main`.
  **Ready to slice.**
- **Governance:** [ADR-0154](../../../docs/adr/0154-manual-scoring-feedback-mechanisms.md).
  Invariants of [ADR-0148](../../../docs/adr/0148-copilot-agent-source-actor-attribution-and-context-only-binding.md)
  (framework-derived actor) and [ADR-0150](../../../docs/adr/0150-s20-reversal-copilot-draft-turn-propose-only.md)
  (propose→confirm) hold throughout.
- **Module scope:** this is **one module of 0.0.4**, in its own subdirectory so it
  does not collide with sibling 0.0.4 tracks. `FR-`/`NFR-`/`PAC-`/`US` numbers in
  this file are **module-scoped** — qualify them as `quality-feedback FR-n` when
  referenced from outside.
- **Baseline:** post-0.0.3 `main` (0.0.3 merged 2026-07-21, as did the
  SimpleTexting migration). This module reuses 0.0.3's L6 loop, admin review
  queue, `metric_event` panel, and Conversation Simulator rather than
  rebuilding them. Reserved numbers against that baseline: **ADR-0154**,
  migration **0012**.
- **Terminology:** Textline is retired (ADR-0153). The governed customer send is
  the provider-neutral `toee_sms_reply`, surfaced as "Send via SMS".

---

## 1. Problem Statement

Hermes produces two streams of AI output that no human systematically scores.

Externally, the **External Customer Service Profile** auto-handles customer
conversations end to end. Supervisors can open the **Auto-Handled Audit View**
and the **Sales Outreach Audit View** and read them, but reading is all they can
do — there is nowhere to record "this one was wrong, and here's why." Quality
judgments live in people's heads and evaporate. Nobody can answer "what fraction
of auto-handled conversations are acceptable?", "what do we get wrong most
often?", or even "which records has anyone actually checked?"

Internally, reps ask the **Internal Copilot Profile** for a draft, then silently
accept it, rewrite it, or throw it away. That behavior is the single most honest
quality signal the system produces — a draft sent untouched is a good draft — and
it is discarded on every turn. When a draft is bad, the rep fixes it in place and
the reason is never recorded.

So the system has no measured notion of its own output quality, and the
improvement loop that 0.0.3 built (agent proposes a learning, human confirms it)
has no human-quality signal feeding it — the agent can only propose from its own
view of a conversation, never from "a supervisor said this reply was wrong."

## 2. Solution

Two **independent** capture mechanisms, both scoring AI output, both
actor-attributed and append-only, sharing a tool shell but no data or policy:

- **External — Interaction Review.** A review bar on the two audit detail routes
  lets a **Workbench Supervisor** or **Workbench Admin** mark one auto-handled
  record or one `sales_outreach` case **pass** or **fail**; fail requires one or
  more fixed **Review Reason Tags** and takes an optional comment. Both audit
  lists gain a Reviewed / Not reviewed column so sampling coverage is visible.
- **Internal — Draft Feedback.** The copilot draft card gains 👍/👎 (👎 expands
  internal reason tags + optional comment), and the governed SMS send
  silently records whether the sent text matched the generated draft
  (`sent_as_is` / `sent_edited` + edit distance). Reps get a zero-effort implicit
  signal and an optional explicit one.

Writes go through one new `toee_feedback` tool reachable **only** on the
deterministic dispatch route and registered in **no** Profile Tool Allowlist, so
every row carries a real employee and no agent can score itself or its own draft.

Phase 1 (this PRD) is capture only. The improvement loop is Phase 2 and, by
decision, **builds nothing new**: it feeds 0.0.3's L6 `agent_experience`
propose→confirm→inject loop and its admin Accept/Reject queue, the existing
KnowledgeOps publish gate, and the existing aggregate metrics panel.

## 3. User Stories

**Supervisor / admin — external review**

1. As a supervisor, I want to mark an auto-handled conversation pass or fail from
   its audit detail page, so that my quality judgment is recorded instead of lost.
2. As a supervisor, I want failing a conversation to require at least one reason
   tag, so that "this was bad" is always actionable rather than a bare opinion.
3. As a supervisor, I want a fixed tag vocabulary (factual error, tone, policy
   violation, tool misuse, missed information, should have escalated, other), so
   that failures aggregate into counts instead of unstructured prose.
4. As a supervisor, I want to add an optional free-text comment, so that an
   unusual failure keeps its detail without forcing a new tag.
5. As a supervisor, I want to review a `sales_outreach` case the same way I review
   an auto-handled record, so that one habit covers both audit routes.
6. As a supervisor, I want the audit list to show which records have been
   reviewed, so that I don't re-check the same conversation or miss a batch.
7. As a supervisor, I want to see my previous verdict when I reopen a record, so
   that I know I already judged it and what I said.
8. As a supervisor, I want to change my mind and re-review a record, so that a
   hasty verdict can be corrected — with the earlier one retained for audit.
9. As a supervisor, I want my review recorded against my account, so that
   judgments are attributable when two reviewers disagree.
10. As an admin, I want reviewing to write a **Workbench Audit Log** entry, so
    that review activity is accountable like every other workbench action.
11. As a supervisor, I want reviewing to be impossible for a rep, so that quality
    scoring stays a supervisory responsibility.
12. As a supervisor, I want the audit views to stay read-only toward conversation
    data, so that scoring never edits the record being scored.

**Rep — internal draft feedback**

13. As a rep, I want to thumbs-up a draft that was good, so that the system learns
    what "good" looks like without me writing anything.
14. As a rep, I want to thumbs-down a draft and pick a reason (factual error,
    wrong tone, missing context, too verbose, wrong action, other), so that a bad
    draft teaches something specific.
15. As a rep, I want rating to be optional and never block drafting or sending, so
    that feedback never slows down customer work.
16. As a rep, I want the system to notice by itself whether I sent the draft
    untouched or edited it first, so that the most useful signal costs me nothing.
17. As a rep, I want a failure to record my feedback to never fail my send, so
    that a telemetry problem can't cost a customer their reply.
18. As a rep, I want my feedback attributed to my account, so that it's clear who
    judged the draft.

**Governance**

19. As an admin, I want the AI to be structurally incapable of submitting feedback
    about itself, so that the quality record can't be gamed by the thing being
    measured.
20. As an admin, I want a model-supplied actor, verdict, or reason inside tool
    params to be ignored, so that feedback can't be forged from a prompt.
21. As an admin, I want feedback rows to be append-only, so that the quality
    history can't be quietly rewritten.
22. As an admin, I want the internal and external mechanisms kept independent
    (separate storage, tags, roles), so that changing one can't silently change
    the other.

**Owner — acceptance**

23. As the owner, I want to drive a conversation in the Conversation Simulator,
    have it auto-handle, and then score it from the audit view, so that the whole
    external loop is provable from the front end.
24. As the owner, I want to generate a copilot draft in the simulator, edit and
    send it, and see both the implicit outcome and my explicit rating recorded, so
    that the internal loop is provable end to end.
25. As the owner, I want every part of this module reachable from a front-end
    entry, so that nothing is testable only by SQL or curl.

**Phase 2 (out of scope here, motivating the shape)**

26. As an admin, I want repeated failures to become proposals in the L6 review
    queue I already use, so that the agent improves without me learning a second
    approval surface.
27. As an admin, I want feedback rates on the metrics panel I already read, so
    that quality trends sit beside the other measures.

## 4. Functional Requirements

- **FR-1 Storage.** Migration `0012_feedback_tables.sql` adds two independent,
  append-only operational-layer tables. `interaction_review`: subject kind
  (`auto_handled_record` | `sales_outreach_case`), subject id, verdict
  (`pass` | `fail`), reason tags, optional comment, reviewer account, timestamp;
  DB-level check that a `fail` carries at least one tag. `draft_feedback`: case
  id, a draft correlation id, draft kind, the generated-draft snapshot, outcome
  (`sent_as_is` | `sent_edited` | `rated_only`), optional edit-distance ratio,
  optional verdict (`up` | `down`), reason tags, optional comment, rep account,
  timestamp; DB-level check that a `down` carries at least one tag. Retention
  follows the operational layer (ADR-0004).
- **FR-2 Reason-tag vocabularies.** Two fixed, separate enums — external
  (`factual_error`, `tone_inappropriate`, `policy_violation`, `tool_misuse`,
  `missed_information`, `should_have_escalated`, `other`) and internal
  (`factual_error`, `wrong_tone`, `missing_context`, `too_verbose`,
  `wrong_action`, `other`). A tag outside the mechanism's own enum is rejected.
- **FR-3 `toee_feedback` tool.** Fixed action enum per ADR-0059:
  `submit_interaction_review`, `record_draft_outcome`, `submit_draft_rating` on
  the **Internal Copilot Profile**, and read-only `list_feedback` on the
  **Supervisor Admin Profile**. Reachable only through
  `POST /v1/tools:dispatch`; registered in **no** Profile Tool Allowlist.
- **FR-4 Actor-attributed, fail-closed writes.** Every write derives its actor
  from framework-resolved `context.user_id` and fails closed to `policy_blocked`
  when it is absent. `submit_interaction_review` additionally requires a
  supervisor/admin role; the draft actions require the acting rep to hold the
  case. `source`, actor, and verdict are never read from tool params.
- **FR-5 External review UI.** A review bar on both audit detail routes: pass in
  one click; fail expands multi-select tags plus an optional comment. An existing
  review by the current account renders with an edit affordance that appends a new
  row. Visible only to supervisor/admin. Submitting writes a **Workbench Audit
  Log** entry. Conversation data stays read-only.
- **FR-6 Review-status column.** Both audit lists show a Reviewed / Not reviewed
  badge derived from the review table.
- **FR-7 Draft correlation and snapshot.** When a draft is produced (chat draft
  card or a Draft action), the client mints a correlation id and retains the
  generated text; subsequent edits mutate only the working copy. Both implicit and
  explicit rows for one draft share the correlation id.
- **FR-8 Explicit draft rating.** 👍/👎 on the draft card; 👎 expands internal tags
  plus an optional comment. Never blocks drafting or sending. A rating with no
  send records outcome `rated_only`.
- **FR-9 Implicit send outcome.** After a successful governed SMS send, record
  `sent_as_is` when the sent text equals the generated snapshot after trimming,
  otherwise `sent_edited` with a normalized edit-distance ratio. Recording is
  fire-and-forget: a failure is logged and never fails the send (FR-17/US-17).
- **FR-10 BFF routes.** `POST /api/copilot/audit/review` and
  `POST /api/copilot/feedback` map to the dispatch actions per ADR-0141, attaching
  the session's actor; no raw tool envelopes reach the browser.
- **FR-11 Mechanism independence.** Separate tables, tag enums, actions, and role
  gates. The only shared artifacts are the tool shell, the migration file, and the
  dispatch plumbing.

## 5. Non-Functional Requirements

- **NFR-1 Three-layer gate per slice** (0.0.3 house rule): ① technical CI,
  ② browser E2E from the front end, creating a front-end entry where none exists,
  ③ owner PAC in the Conversation Simulator. Pure-refactor slices may satisfy ①
  alone and must name the exemption.
- **NFR-2 Live, not mock.** Every persistence assertion reads back from Postgres
  directly rather than trusting a tool return value.
- **NFR-3 Eval neutrality.** Phase 1 injects nothing into any turn and adds no
  agent-callable tool, so the ADR-0121 record/replay pin is untouched and no new
  eval scenarios are required. Any Phase 2 path that reaches a turn is
  eval-sensitive and re-opens this.
- **NFR-4 No new governance surface.** Phase 2 reuses the L6 review queue, the
  KnowledgeOps publish gate, and the metrics panel; it introduces no second
  approval UI and no bespoke dashboard.
- **NFR-5 Migration safety.** Additive only — two new tables, no change to
  existing tables, no backfill.
- **NFR-6 Docs.** ADR-0154 ships with the build; CONTEXT.md gains **Interaction
  Review**, **Draft Feedback**, **Review Reason Tag**, **Improvement Proposal**
  and their relationships, re-applied onto post-0.0.3 CONTEXT.md.

## 6. Implementation Decisions

- **Two tables, not one polymorphic table.** The mechanisms have different
  subjects, tag vocabularies, role gates, and futures; one table with nullable
  halves would encode "independent" as a convention instead of a schema.
- **Append-only, latest-per-reviewer on read.** Re-review is a new row.
  Correcting a verdict must not erase that an earlier verdict existed, and the
  0.0.2 audit-honesty precedent (ADR-0148) argues for retention over mutation.
- **Whole-interaction verdicts, not per-turn.** Matches how supervisors already
  sample in the audit views; per-turn scoring multiplies review cost for
  granularity nobody has asked for yet.
- **The subject is the audit record identity**, not the long-lived thread — a
  thread accumulates many interactions, so scoring it would make the verdict
  ambiguous the moment a second conversation lands.
- **Dispatch-only tool, absent from every allowlist.** This is what makes
  "the AI cannot score itself" structural. The copilot draft turn boots through a
  path that takes no `user_id` at all (ADR-0148's invariant), so an agent-initiated
  feedback call cannot carry an actor and fails closed — a property of the boot
  path, not of a prompt instruction.
- **Client-minted draft correlation id.** The draft is currently just a mutable
  string in the gateway component; correlating an implicit outcome with an explicit
  rating, and computing edit distance at all, requires an id plus the original
  snapshot. This is the one genuinely new piece of client state.
- **Fire-and-forget outcome recording.** Quality telemetry must never be able to
  break a customer reply.
- **Phase 2 feeds existing machinery.** Operational-learning proposals become
  `agent_experience` proposed rows carrying a distinguishing source; knowledge
  gaps become knowledge-slot drafts through `submit_for_eval`; counters become
  `metric_event` rows. This was the decisive finding of the 0.0.3 gap analysis.

## 7. Testing Decisions

**What makes a good test here:** it asserts externally observable behavior — a
row in Postgres, a rendered state, a blocked call — not the shape of an internal
resolver. Governance tests assert the *refusal*, not the code path that refuses.

**Seams, preferring existing and highest:**

- **Primary — `POST /v1/tools:dispatch`.** All four actions cross it, and Tool
  Gate, actor attribution, and validation resolve there. One seam covers the
  governance-critical surface. Existing seam with 0.0.2 precedent
  (`test_datastore_driver_memory.py`, `test_customer_memory_write_source.py`).
- **Secondary — live-Postgres read-back.** Direct `SELECT` after each write.
- **Tertiary — UI component tests** (`*.test.tsx`, existing pattern beside
  `AutoHandledDetail.tsx` / `CopilotGateway.tsx`) and the BFF route handlers.

No new seam is proposed. **Confirm this matches expectations before slicing.**

**Layer ① technical.** At the dispatch seam: missing actor → `policy_blocked`;
rep attempting an interaction review → `policy_blocked`; unclaimed case →
`policy_blocked`; `fail`/`down` without tags → validation error; foreign tag →
validation error; model-supplied actor/verdict/source in params ignored. Live
Postgres: every write path read back; append-only proven by two reviews from one
reviewer yielding two rows with latest-wins on read; `sent_as_is` vs
`sent_edited` classification including the trim boundary. Components: review bar
unreviewed / reviewed / fail-expansion / role-hidden states; rating flow;
send-outcome capture; and outcome-recording failure not blocking the send.

**Layer ② browser E2E.** Submit a review on each audit detail route and see the
list's status column change.

**Layer ③ owner PAC.** PAC-1: in the simulator, drive a conversation to an
auto-handled interaction, score it fail with tags from the audit view, confirm the
row and the audit-log entry. PAC-2: drive a case to a copilot draft, thumbs-down
with a tag, edit and send, confirm both the explicit rating and `sent_edited`
with a plausible ratio, sharing one correlation id. PAC-3: confirm a rep account
sees no review controls.

**Prior art:** 0.0.2's governance tests are the model for layers ① — particularly
the removal-tripwire pattern (assert the forbidden write produces *zero* rows),
which applies directly to "an agent-initiated feedback call persists nothing."

## 8. Out of Scope

- The Phase 2 improvement loop itself — aggregation, proposal generation, and the
  routing into L6 / KnowledgeOps / metrics. Shape is decided (§6) but nothing is
  built until Phase 1 accumulates a real feedback distribution.
- Any autonomous self-modification: feedback never writes to agent memory,
  prompts, or published knowledge without a human decision and the applicable gate.
- Per-turn external scoring; 1–5 numeric scales; reviewer-disagreement workflows.
- Implicit outcome capture for email and internal-note drafts — those leave by
  manual copy with no send event, so they carry explicit ratings only. Revisit if
  a governed email send ships.
- A dedicated feedback dashboard or `/admin/feedback` route.
- Customer-facing satisfaction ratings — this module scores AI output for
  internal use, and nothing here is exposed to customers.
- Changing the audit views' read-only stance toward conversation data.

## 9. Further Notes

- **Sequencing.** Unblocked — 0.0.3 is on `main` and this branch is rebased onto
  it. Ready to slice into issues.
- **Numbering is reserved, not held.** ADR-0154 and migration 0012 were free at
  rebase time, but sibling 0.0.4 tracks are landing concurrently and both
  namespaces are first-come. This module already lost 0149→0153→0154 and
  0008→0010→0012 to two such races; **re-check both immediately before the
  implementation PR** rather than trusting these numbers.
- **Known open risk (inherited).** Both mechanisms' honesty rests on
  `context.user_id`'s own contract — ADR-0148's RK-2. A future non-UI caller that
  sets `user_id` without a real employee present would forge feedback attribution
  exactly as it would forge a memory write. Documented, not closed.
- **Tag vocabularies are migrations to change.** Deliberate: they are the
  aggregation keys Phase 2 depends on. Expect one re-cut after real data arrives.
- **Volume expectation.** Implicit draft outcomes will vastly outnumber explicit
  ratings and reviews. Phase 2 aggregation should weight accordingly rather than
  treating one row as one opinion.
