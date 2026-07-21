# Manual scoring feedback mechanisms — design (Phase 1: dual-side capture)

Date: 2026-07-21
Status: approved by product owner (grilling session, this date)
Related: ADR-0149 (this design's governance decisions), ADR-0148 (actor
attribution invariant this design reuses), ADR-0037/0085/0086 (audit views),
ADR-0083 (governed send flow), ADR-0059 (tool action enums), ADR-0004
(retention).

## Goal

Give humans a governed way to score Hermes AI output, capture that feedback as
structured data, and (Phase 2) let the AI aggregate it into improvement
proposals that humans approve through the existing eval gates. Two independent
mechanisms:

- **External (对外)**: supervisors/admins score AI auto-handled customer
  conversations from the read-only audit views — **Interaction Review**.
- **Internal (对内)**: reps' interaction with copilot drafts produces implicit
  and explicit quality signals — **Draft Feedback**.

Phase 1 (this design) builds capture on both sides. Phase 2 (sketch only)
builds the proposal loop, informed by the real feedback distribution Phase 1
accumulates.

## Decisions locked during grilling

| Question | Decision |
| --- | --- |
| External review subject | Whole-interaction verdict on the existing audit record identity: `auto_handled_record` (the audit `recordId`) or `sales_outreach_case` (case id) — not the long-lived thread |
| Internal signal source | Implicit outcome (sent as-is / sent edited, captured at governed send) + lightweight explicit 👍/👎 on the draft card |
| Feedback → improvement | Governed loop only: AI proposes, humans approve, eval gates publish. No autonomous self-modification, no ungated memory writes (Phase 2) |
| Scale | Pass/fail + fixed reason tags + optional comment (not 1–5) |
| Approach | Reuse governance skeleton: 2 Postgres tables, UI embedded in existing surfaces, one new `toee_feedback` tool, no new routes |
| Scope | Both capture sides in Phase 1; proposal loop is Phase 2 |
| Re-review semantics | Append-only; UI shows latest per reviewer; history retained |
| Audit lists | Add a Reviewed / Not reviewed status column to both audit lists |
| Tag sets | Confirmed (below); fixed enums, per-mechanism, English UI |

## 1. Data model

New migration `hermes-runtime/migrations/0008_feedback_tables.sql`. Two
independent tables in the operational layer (Toee Business Datastore).
Retention follows the operational layer (ADR-0004).

### `interaction_review` (external)

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | uuid |
| `subject_kind` | TEXT NOT NULL | CHECK IN (`auto_handled_record`, `sales_outreach_case`) |
| `subject_id` | TEXT NOT NULL | audit record id or case id |
| `verdict` | TEXT NOT NULL | CHECK IN (`pass`, `fail`) |
| `reason_tags` | TEXT[] | CHECK: non-empty when `verdict='fail'`; values from external tag enum |
| `comment` | TEXT NULL | free text, optional |
| `reviewer_account_id` | TEXT NOT NULL | framework-resolved actor |
| `created_at` | timestamptz NOT NULL | |

Append-only: no UPDATE path; a re-review inserts a new row. Reads take the
latest row per `(subject_kind, subject_id, reviewer_account_id)`. Index on
`(subject_kind, subject_id, created_at DESC)`.

External tag enum: `factual_error`, `tone_inappropriate`, `policy_violation`,
`tool_misuse`, `missed_information`, `should_have_escalated`, `other`.

### `draft_feedback` (internal)

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | uuid |
| `case_id` | TEXT NOT NULL | the claimed Human Intervention Case |
| `draft_client_id` | TEXT NOT NULL | client-generated uuid minted when a draft is created; correlates implicit + explicit rows for the same draft |
| `draft_kind` | TEXT NOT NULL | CHECK IN (`sms`, `email`, `note`) |
| `draft_text` | TEXT NOT NULL | snapshot of the *original generated* draft |
| `outcome` | TEXT NOT NULL | CHECK IN (`sent_as_is`, `sent_edited`, `rated_only`) |
| `edit_distance_ratio` | REAL NULL | set on `sent_edited` (normalized Levenshtein vs original) |
| `verdict` | TEXT NULL | CHECK IN (`up`, `down`) |
| `reason_tags` | TEXT[] | CHECK: non-empty when `verdict='down'`; values from internal tag enum |
| `comment` | TEXT NULL | |
| `rep_account_id` | TEXT NOT NULL | framework-resolved actor |
| `created_at` | timestamptz NOT NULL | |

Append-only. `sent_as_is` = final text equals original snapshot after trim;
otherwise `sent_edited` + ratio. Explicit rating without a send records
`rated_only`.

Internal tag enum: `factual_error`, `wrong_tone`, `missing_context`,
`too_verbose`, `wrong_action`, `other`.

Known Phase 1 gap (accepted): only the governed Textline send produces an
implicit outcome. Email and note drafts leave via manual copy — no send event
— so they carry explicit ratings only.

## 2. Tool surface: `toee_feedback`

Fixed action enum (ADR-0059), reachable **only** through the deterministic
`POST /v1/tools:dispatch` route. **Not registered in any Profile Tool
Allowlist** — no agent (external, copilot draft turn, or admin) can call it.

| Action | Profile | Tool Gate |
| --- | --- | --- |
| `submit_interaction_review` | `internal_copilot` (audit routes live under `/copilot`) | `context.user_id` present AND role supervisor/admin; else `policy_blocked` |
| `record_draft_outcome` | `internal_copilot` | `context.user_id` present AND actor has the case claimed |
| `submit_draft_rating` | `internal_copilot` | same as above |
| `list_feedback` | `supervisor_admin` | read-only; reserved for Phase 2 analysis and admin inspection |

Governance invariants (extends ADR-0148):

- Every feedback write is actor-attributed from `context.user_id` —
  framework-derived only, fail-closed when absent. Model-supplied
  `user_id`/`verdict`/`reviewer` params are ignored.
- Because the copilot draft turn's boot path (`boot_profile`) structurally
  cannot carry `user_id`, **the AI can never score itself** — a structural
  guarantee, not a prompt rule.
- Validation: `fail`/`down` without at least one valid reason tag is a
  validation error; tags outside the mechanism's enum are rejected.

## 3. UI (embedded in existing surfaces, no new routes)

### External — audit detail pages

`AutoHandledDetail.tsx` and `SalesOutreachDetail.tsx` gain a review bar below
the summary header card (mockup A, approved):

- Pass = one click. Fail expands fixed tag chips (multi-select) + optional
  comment + submit.
- If the current account already reviewed this subject, show the latest
  verdict/tags with an edit affordance (which appends a new row).
- Visible to supervisor/admin only; submitting writes a **Workbench Audit
  Log** entry. The audit surfaces remain read-only with respect to
  conversation data — reviews write to the review table only.

`AutoHandledList.tsx` / `SalesOutreachList.tsx` gain a review-status column
(Reviewed / Not reviewed badge) so supervisors can see sampling coverage.

### Internal — copilot draft card + governed send

`CopilotGateway.tsx`:

- Mint `draft_client_id` (uuid) and keep the original draft text snapshot when
  a draft is generated (chat `draftCard` or Draft buttons); editing mutates
  only the working copy.
- Draft card header gains 👍/👎 (mockup B, approved). 👎 expands internal tag
  chips + optional comment. Rating never blocks drafting or sending.

`GovernedSendModal.tsx` confirm path: after a successful governed send,
silently record the outcome (`sent_as_is`/`sent_edited` + ratio) via the BFF.
Outcome recording failure must not fail the send (fire-and-forget with error
logged).

### BFF (ADR-0141 pattern)

- `POST /api/copilot/audit/review` → `submit_interaction_review`
- `POST /api/copilot/feedback` → `record_draft_outcome` / `submit_draft_rating`
  (body discriminates)

Both attach `actor_account_id` from the session as the dispatch route already
does; no raw tool envelopes in the browser.

## 4. Independence of the two mechanisms

Separate tables, separate tag enums, separate actions, separate role gates,
and (Phase 2) separate proposal pipelines and publish gates. Shared: the
`toee_feedback` tool shell, the migration file, and the dispatch plumbing —
shared skeleton, not shared data or policy.

## 5. Phase 2 sketch (not built now)

A Supervisor Admin Profile analysis task (manually triggered at first) uses
`list_feedback` to aggregate unaddressed `fail`/`down` feedback and generate
**Improvement Proposals** of three kinds:

1. Knowledge-slot revision draft → existing KnowledgeOps `submit_for_eval` →
   **Knowledge Publish Eval Gate**.
2. New **Launch Eval Scenario** suggestion (YAML fixture draft, human-reviewed
   before landing).
3. Internal draft-persona adjustment draft → parallel eval + human approval.

Approval UI lands in `/admin` (master-detail pattern). Concrete Phase 2 design
waits for the real feedback distribution from Phase 1. No autonomous
self-modification; no direct feedback-to-memory writes.

## 6. Testing

- **Unit (resolver/gate)**: no actor → `policy_blocked`; insufficient role →
  `policy_blocked`; `fail`/`down` without tags → validation error; tags
  outside enum → validation error; model-supplied actor/verdict params
  ignored.
- **Datastore (live Postgres)**: each write path SELECTed back directly
  (source-of-truth proof, matching 0.0.2 practice); append-only proven (two
  reviews by one reviewer → two rows, latest wins on read).
- **UI component tests**: review bar states (unreviewed / reviewed / fail
  expansion / role-hidden), draft card rating flow, send-outcome capture
  (as-is vs edited), outcome failure does not block send.
- No new eval scenarios in Phase 1: `toee_feedback` is not agent-callable, so
  there is no agent behavior to evaluate.

## 7. Documentation

- CONTEXT.md: new terms **Interaction Review**, **Draft Feedback**, **Review
  Reason Tag**, **Improvement Proposal** + relationships.
- ADR-0149: manual scoring feedback mechanisms (governance decisions).
