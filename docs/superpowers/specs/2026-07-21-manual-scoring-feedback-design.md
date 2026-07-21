# Manual scoring feedback mechanisms — design (Phase 1: dual-side capture)

Date: 2026-07-21
Status: approved by product owner (grilling session, this date), then revised
the same day after a gap analysis against the unmerged `feat/0.0.3-land-all`
branch (see §0).
Target: **0.0.4, on the post-0.0.3 baseline.** Do not implement until 0.0.3
merges to `main`. Module PRD: `workspace/0.0.4/quality-feedback/PRD.md`.
Related: ADR-0154 (this design's governance decisions), ADR-0148 (actor
attribution invariant this design reuses), ADR-0037/0085/0086 (audit views),
ADR-0083 (governed send flow), ADR-0059 (tool action enums), ADR-0004
(retention), and from 0.0.3: ADR-0150 (propose→confirm), ADR-0152 (L6
agent-experience loop), ADR-0121 (eval record/replay pin).

## 0. Revision after the 0.0.3 gap analysis

This design was first written on a `main` (0.0.2) worktree, blind to the
unmerged 0.0.3 branch. Reconciling against it changed four things:

1. **Migration number** — 0.0.3 takes `0008`/`0009`, and the post-0.0.3 merges
   take `0010_customer_memory_retention_index.sql` and
   `0011_inbound_event_claim.sql`; this feature's migration is **0012**.
2. **ADR number** — 0.0.3 takes 0149–0152 and the SimpleTexting migration took
   0153; this ADR is **0154**.
2b. **Textline is retired** (ADR-0153) — the governed send is provider-neutral
   `toee_sms_reply` / "Send via SMS", so this design says SMS, not Textline.
3. **Phase 2 builds no new pipeline.** 0.0.3 already ships the L6
   `agent_experience` propose→confirm→inject loop, its admin Accept/Reject
   queue, a proposal audit surface, and an aggregate metrics panel backed by
   `metric_event`. Phase 2 feeds those; it does not duplicate them.
4. **Testing adopts 0.0.3's three-layer gate** — technical CI, browser E2E
   creating a front-end entry, and owner PAC in the **Conversation
   Simulator** — replacing the original unit/datastore/component-only plan.

Phase 1 capture (**Interaction Review**, **Draft Feedback**) survived the
analysis unchanged: 0.0.3 has no conversation-quality scoring and no
draft-quality signal, so it is genuinely net-new.

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

New migration `hermes-runtime/migrations/0012_feedback_tables.sql` (0008–0011
are taken). Two independent tables in the operational layer (Toee Business
Datastore). Retention follows the operational layer (ADR-0004).

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

Known Phase 1 gap (accepted): only the governed SMS send produces an
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

## 5. Phase 2 sketch (not built now) — feeds existing machinery

A Supervisor Admin Profile analysis task (manually triggered at first) uses
`list_feedback` to aggregate unaddressed `fail`/`down` feedback and route it
into surfaces 0.0.3 already ships — **no new proposal pipeline, no new
approval queue, no new dashboard**:

1. **Operational-learning proposals** (tone, procedure, tool-usage patterns) →
   the existing L6 `agent_experience` store as `status='proposed'` rows via the
   governed propose path, decided on the existing admin Accept/Reject queue,
   injected only once confirmed (ADR-0152). Feedback-derived proposals carry a
   distinguishing source so the queue can show where a proposal came from.
2. **Knowledge-gap proposals** (`factual_error` / `missed_information` clusters)
   → knowledge-slot revision draft → existing KnowledgeOps `submit_for_eval` →
   **Knowledge Publish Eval Gate**.
3. **New Launch Eval Scenario suggestions** → YAML fixture draft, human-reviewed
   before landing.

Feedback counters (review pass rate, draft acceptance rate, top failing reason
tags) are emitted as `metric_event` rows onto the existing aggregate metrics
panel. Concrete Phase 2 design waits for the real feedback distribution from
Phase 1. No autonomous self-modification; no direct feedback-to-memory writes.

**Eval sensitivity.** Anything that ends up injected into a turn (path 1's
confirmed L6 entries, path 2's published knowledge) is eval-sensitive and must
respect the ADR-0121 record/replay pin — the same constraint ADR-0152 already
carries. Phase 1 itself injects nothing.

## 6. Testing

Every slice passes 0.0.3's **three-layer gate**: ① technical CI, ② browser E2E
from the front end (creating a front-end entry where none exists), ③ owner PAC
in the **Conversation Simulator**.

**Seams** — preferring existing, highest-possible seams:

- **Primary: `POST /v1/tools:dispatch`.** All four `toee_feedback` actions flow
  through it, and Tool Gate, actor attribution, and validation all resolve
  there. One seam covers the governance-critical surface. Existing seam
  (0.0.2 precedent).
- **Secondary: live-Postgres read-back.** Assertions SELECT from Postgres
  directly rather than trusting a tool return value (0.0.2 "live, not mock"
  proof principle).
- **Tertiary: UI component tests** (existing `*.test.tsx` seam) and the
  workbench BFF routes.

**Layer ① technical:**

- Gate/validation at the dispatch seam: no actor → `policy_blocked`;
  insufficient role → `policy_blocked`; `fail`/`down` without tags →
  validation error; tags outside the mechanism's enum → validation error;
  model-supplied actor/verdict params ignored.
- Live Postgres: each write path SELECTed back; append-only proven (two
  reviews by one reviewer → two rows, latest wins on read).
- UI components: review bar states (unreviewed / reviewed / fail expansion /
  role-hidden), draft rating flow, send-outcome capture (as-is vs edited),
  and outcome-recording failure not blocking the send.

**Layer ② browser E2E:** review bar reachable and submittable on both audit
detail routes; review-status column reflects the result on the list.

**Layer ③ owner PAC:** in the simulator — drive a conversation to an
auto-handled interaction, then score it from the audit view; drive a case to a
copilot draft, then rate it and send edited, and confirm both rows land.

**Eval:** no new eval scenarios in Phase 1 — `toee_feedback` is not
agent-callable and injects nothing, so there is no agent behavior to evaluate
and the record/replay pin is untouched.

## 7. Documentation

- CONTEXT.md: new terms **Interaction Review**, **Draft Feedback**, **Review
  Reason Tag**, **Improvement Proposal** + relationships. These were authored
  on the 0.0.2 base and must be re-applied onto post-0.0.3 CONTEXT.md, which
  minted its own glossary terms in the same file.
- ADR-0154: manual scoring feedback mechanisms (governance decisions).
