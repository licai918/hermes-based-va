# S01 report — spec correction: dispatch-only pattern + numbering re-check

Branch: `claude/qf-impl` (worktree `.../worktrees/qf-impl`)
Slice: `workspace/0.0.4/quality-feedback/issues/S01-spec-correction-allowlist-and-numbering.md`

## What was verified before editing

- `hermes/toee_hermes/plugin/__init__.py::_AGENT_EXCLUDED_ACTIONS` (line 109) and
  its use in `_register` (line 255: `if (entry["tool"], entry["action"]) in
  _AGENT_EXCLUDED_ACTIONS: continue`) — confirms tools like `toee_agent_experience`,
  `toee_metrics`, `toee_retention`, `toee_job_queue`, `toee_integrations` are
  allowlisted (toolset in `allow`) but have specific actions skipped when building
  the model-callable schema.
- `hermes/toee_hermes/plugin/profiles.py::PROFILE_TOOL_ALLOWLIST` (line 26) —
  confirms the allowlist is keyed by toolset (tool name), not action; `toee_job_queue`
  and `toee_integrations` in the `SUPERVISOR` profile are the direct precedent for
  "allowlisted-but-agent-excluded."
- `hermes-runtime/hermes_runtime/tool_dispatch_app.py::profile_allowlist_gate`
  (line 66) — confirms the dispatch route's Tool Gate literally *is*
  `allowlisted_tools(profile)`; a tool outside it returns `policy_blocked` before
  reaching a driver.
- `ls hermes-runtime/migrations/` — high-water mark is `0017_honored_rate_aggregate.sql`;
  `0016_scripted_eval_turn.sql` also present. Both `0016` and `0017` are taken,
  contradicting the S01 issue file's own "0017 provisional" note (which predates
  the `0017_honored_rate_aggregate` landing). Per the orchestrating task's explicit
  instruction, treated `0018`/`0019` as the corrected provisional values, superseding
  the stale `0017` in the issue file itself.

## Files changed

### 1. `docs/adr/0154-manual-scoring-feedback-mechanisms.md`

Decision 3 rewritten. Before:

> **Append-only, actor-attributed writes via a dispatch-only tool.** New
> `toee_feedback` tool (fixed action enum) is reachable only through
> `POST /v1/tools:dispatch` and registered in **no** Profile Tool Allowlist.
> Every write requires framework-resolved `context.user_id` (fail-closed) —
> by the ADR-0148 boot-path invariant, an agent draft turn can never carry
> one, so **the AI structurally cannot score itself**. Re-review appends; the
> audit trail keeps history.

After:

> **Append-only, actor-attributed writes; allowlisted for dispatch, excluded
> from the model's tool loop.** New `toee_feedback` tool (fixed action enum)
> is added to the Internal Copilot and Supervisor Admin profiles'
> `PROFILE_TOOL_ALLOWLIST` — the dispatch route's Tool Gate *is* that
> allowlist, so a tool absent from it would return `policy_blocked` and be
> unreachable even for the BFF. What keeps a live agent from calling it is the
> separate, per-action `_AGENT_EXCLUDED_ACTIONS` set: every `(toee_feedback,
> action)` pair is listed there, so tool registration skips it when building
> the model's callable schema and it never reaches the model surface — the
> same pattern already used by `toee_agent_experience`, `toee_metrics`,
> `toee_retention`, `toee_job_queue`, and `toee_integrations`. The tool is
> reachable only through `POST /v1/tools:dispatch`. Allowlisting is per
> **tool**, not per action — `toee_feedback`'s own action-level split
> (`submit_interaction_review` on Internal Copilot vs. `list_feedback` on
> Supervisor Admin) is enforced by which BFF route calls which action, not by
> the allowlist. The load-bearing guarantee that **the AI structurally cannot
> score itself** is independent of any of this registration plumbing: every
> write requires framework-resolved `context.user_id` (fail-closed), and by
> the ADR-0148 boot-path invariant the copilot draft turn's boot path carries
> no acting employee at all, so an agent-initiated feedback write fails closed
> on the actor check regardless of registration. Re-review appends; the audit
> trail keeps history.

Governance claim ("AI cannot score itself") preserved and now explicitly named as
resting on the boot-path/actor-check argument, independent of allowlist/exclusion
plumbing. No migration-number reference existed in this file (it only reserves
the ADR's own number, 0154, which is correct and untouched) — brief's "ADR-0154
already landed and needs no renumber" confirmed, no edit needed there.

### 2. `workspace/0.0.4/quality-feedback/PRD.md`

Five edits:

- **Header reserved-numbers line** (was: `migration **0012**.`) → now:
  `migration **0018** (provisional — see §9, re-check at PR time).`
- **§2 Solution** paragraph (was: `...reachable **only** on the deterministic
  dispatch route and registered in **no** Profile Tool Allowlist, so every row
  carries a real employee and no agent can score itself...`) → rewritten to the
  allowlist+agent-excluded pattern, with the "real employee" guarantee reattributed
  to the boot-path argument rather than to non-registration.
- **FR-1** (was: `Migration \`0012_feedback_tables.sql\` adds...`) → now:
  `` Migration `0018_feedback_tables.sql` (next free number, re-checked immediately
  before the migration PR — see §9) adds... ``
- **FR-3** (was: `...registered in **no** Profile Tool Allowlist.`) → now states
  `toee_feedback` **is** in both profiles' allowlist, every action is in the
  agent-excluded set, and adds the new sentence: "Allowlisting is per-**tool**:
  the split between which action lives on which profile ... is enforced by which
  BFF route calls which action, not by the allowlist itself." — this is the
  brief's required "per-tool not per-action" record.
- **§6 Implementation Decisions**, "Dispatch-only tool, absent from every
  allowlist" bullet → renamed "Dispatch-only tool, allowlisted but agent-excluded"
  and rewritten to the corrected pattern, same boot-path independence framing.
- **§9 Further Notes**, "Numbering is reserved, not held" bullet → rewritten:
  ADR-0154 confirmed as needing no renumber; migration history extended to
  `0012→0016→0017`; next free number recorded as **0018** (S03 `interaction_review`)
  with **0019** next in line (S06 `draft_feedback`), both marked provisional,
  re-check-at-PR-time phrasing kept.

### 3. `docs/superpowers/specs/2026-07-21-manual-scoring-feedback-design.md`

Not explicitly required by the brief's word-for-word Approach list beyond the §0
migration number, but the same wrong "not registered in any allowlist" claim
existed verbatim in §2 (Tool surface), so it was corrected too for ADR/PRD/design-spec
agreement (this doc is cross-referenced by ADR-0154's header and would otherwise
still contradict it):

- **§0 revision note, item 1** — migration number history extended and corrected
  to point at 0018/0019, cross-referencing PRD §9.
- **§1 Data model** — migration filename `0012_feedback_tables.sql` → `0018_feedback_tables.sql`,
  with the same rotted-number history spelled out.
- **§2 Tool surface** (was: `**Not registered in any Profile Tool Allowlist** — no
  agent (external, copilot draft turn, or admin) can call it.`) → rewritten to the
  allowlist+`_AGENT_EXCLUDED_ACTIONS` pattern, with the same per-tool-not-per-action
  clarification.

### 4. `workspace/0.0.4/quality-feedback/issues/README.md`

One line fixed (the seam-findings table already correctly recorded the *corrected*
pattern in row "Structural" — it was the historical narrative used to justify why
S01 exists, not a live claim, so left alone): the migration-rot table row updated
from `0012→0016→**0017**` to `0012→0016→0017→**0018**`.

### 5. `workspace/0.0.4/quality-feedback/issues/S01-spec-correction-allowlist-and-numbering.md`

Item 2 body updated: added `0017_honored_rate_aggregate` to the concurrent-landings
list (confirmed via `ls`), and changed the "next free number" from `0017` to `0018`
(interaction_review, S03) with `0019` noted as next in line (draft_feedback, S06).

### 6. `workspace/0.0.4/quality-feedback/issues/S03-interaction-review-write-path.md`

Two `0017 provisional` occurrences (Surface line, Approach bullet) → `0018 provisional`,
so it stays consistent with the PRD/ADR/design-spec correction. `S06-draft-rating-write-path.md`
did not hardcode a number (`"next free after S03's, re-checked at PR time"`) so needed
no edit.

## Grep verification (orchestrator-specified command)

```
grep -rn "no profile tool allowlist\|registered in NO\|0016_feedback\|0017 provisional" docs/ workspace/0.0.4/quality-feedback/
```

Output: **empty** (exit code 1 / no matches).

Additional case-insensitive sweep (`registered in no\|no profile tool allowlist`)
turns up only historical/narrative uses that describe the *old, wrong* claim as
context for why S01 exists (S01 issue file's own problem statement, the PRD's
"Dispatch-only tool, allowlisted but agent-excluded" bullet quoting the rejected
phrasing, and README's seam-findings table) — none of these assert the wrong
pattern as current truth.

Remaining `0012` references in the module's docs are all either (a) the correct,
already-landed, unrelated `0012_outbound_send` migration referenced in
`hermes-runtime/*.py` (out of scope, untouched), or (b) historical narrative
explaining the `0012 → 0016 → 0017 → 0018` rot chain — not stale claims that the
feedback migration is `0012`.

ADR-0154, the PRD, and the design spec now agree with each other on both corrections:
- Pattern: `toee_feedback` is allowlisted per-tool in `internal_copilot` +
  `supervisor_admin`, and every `(tool, action)` pair is in `_AGENT_EXCLUDED_ACTIONS`.
- Number: migration `0018_feedback_tables.sql` (S03, `interaction_review`),
  `0019` (S06, `draft_feedback`), both provisional/re-check-at-PR-time.

## Commit

Commit hash: `bda7481` — "docs(0.0.4/quality-feedback): S01 - correct dispatch-only pattern + migration 0018"

## Scope discipline

No code files touched — only Markdown under `docs/` and `workspace/0.0.4/quality-feedback/`.
Did not renumber ADR-0154 itself (correctly landed, per brief). Did not touch
migration files.
