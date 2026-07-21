# Manual scoring feedback: dual-side capture, actor-attributed, proposal-gated improvement

> **Status: Accepted — design approved 2026-07-21** (grilling session with
> product owner). **Targets 0.0.4**, on the post-0.0.3 baseline now on `main`.
> Design spec:
> `docs/superpowers/specs/2026-07-21-manual-scoring-feedback-design.md`;
> module PRD: `workspace/0.0.4/quality-feedback/PRD.md`.
> Builds on ADR-0148 (actor attribution invariant), ADR-0037/0085/0086 (audit
> views), ADR-0083 (governed send), ADR-0059 (action enums), and — from 0.0.3 —
> ADR-0150 (propose→confirm as the governance pattern) and ADR-0152 (the L6
> agent-experience propose→confirm→inject loop this design feeds rather than
> duplicates). The governed send is the provider-neutral `toee_sms_reply` per
> ADR-0153; Textline is retired.
>
> Numbered 0154: 0.0.3 landed 0149–0152 and the SimpleTexting migration
> landed 0153.

## Context

Hermes output quality had no human scoring signal: supervisors could only
passively sample audit views, and rep interaction with copilot drafts (accept,
edit, discard) was unrecorded. The product owner wants a
score → feed-back-to-AI → self-optimize loop inside the Copilot Workbench,
with **independent internal and external mechanisms**. The repo's governance
culture (Tool Gate over prompts, eval gates before publish, ADR-0148's
framework-derived attribution) constrains how such a loop may close.

## Decision

1. **Two independent mechanisms.** External: **Interaction Review** —
   supervisor/admin pass/fail on one `auto_handled_record` or
   `sales_outreach_case` audit subject, from the read-only audit views.
   Internal: **Draft Feedback** — implicit outcome (`sent_as_is` /
   `sent_edited`, captured at governed SMS send) plus optional explicit
   👍/👎 on the draft card. Separate tables, separate fixed **Review Reason
   Tag** enums, separate role gates, separate (future) proposal pipelines.
2. **Pass/fail + fixed reason tags, not a 1–5 scale.** Binary verdicts are
   consistent across raters; fixed tags are aggregable structure. Free-text
   comment is optional color, never required.
3. **Append-only, actor-attributed writes via a dispatch-only tool.** New
   `toee_feedback` tool (fixed action enum) is reachable only through
   `POST /v1/tools:dispatch` and registered in **no** Profile Tool Allowlist.
   Every write requires framework-resolved `context.user_id` (fail-closed) —
   by the ADR-0148 boot-path invariant, an agent draft turn can never carry
   one, so **the AI structurally cannot score itself**. Re-review appends; the
   audit trail keeps history.
4. **The improvement loop is proposal-gated, not autonomous, and reuses
   0.0.3's existing machinery (Phase 2).** Aggregated feedback yields
   **Improvement Proposals** that become effective only after human approval
   and the applicable eval gate. Feedback never writes directly into agent
   memory, prompts, or published knowledge. Crucially, Phase 2 **builds no new
   proposal pipeline**: operational-learning proposals ride the existing L6
   `agent_experience` propose→confirm→inject loop and its admin Accept/Reject
   queue (ADR-0152); knowledge-gap proposals ride the existing KnowledgeOps
   `submit_for_eval` → **Knowledge Publish Eval Gate**; and feedback counters
   are emitted as `metric_event` rows onto the existing aggregate metrics panel
   rather than a bespoke dashboard.

## Consequences

- Sampling coverage becomes visible (review-status column on audit lists) and
  reviews are attributable and auditable like every other workbench action.
- Implicit draft signals cover only the governed SMS send in Phase 1; email
  and note drafts (manual copy-out) carry explicit ratings only — accepted gap.
- Tag enums are migrations to change; Phase 2 may re-cut them once real
  feedback distribution exists.
- A future caller that sets `context.user_id` without a real employee at the
  keyboard would forge feedback attribution — the same RK-2 exposure ADR-0148
  documents; reviews of `user_id` provenance changes must consider this table.

## Considered options

- **1–5 scoring scale (rejected):** poor inter-rater consistency, weak
  aggregation value versus reason tags.
- **Feedback auto-written into profile memory/agent notes (rejected):**
  bypasses eval gates, conflicts with ADR-0033/0148 governance direction,
  prompt-pollution risk.
- **Every failed conversation auto-becomes an eval fixture (deferred):**
  retained as one Phase 2 proposal type, not the sole mechanism — cost per
  fixture is high and tone-class failures don't fixture well.
- **Standalone /admin/feedback subsystem with dashboards (rejected):** largest
  surface, no data yet to justify it — and 0.0.3 already ships an aggregate
  metrics panel plus an L6 review queue, so a parallel dashboard and a parallel
  approval queue would duplicate shipped machinery.
- **A second, feedback-specific propose→confirm pipeline (rejected):** the
  0.0.3 L6 loop (ADR-0150/0152) already encodes propose→confirm→inject with a
  human gate and an audit trail. Feeding it costs a proposal-source field;
  duplicating it costs a whole subsystem and a second governance surface to
  keep honest.
- **Per-turn external scoring (rejected for Phase 1):** finer granularity at
  much higher review cost; whole-interaction verdicts match the existing
  audit-sampling workflow.
