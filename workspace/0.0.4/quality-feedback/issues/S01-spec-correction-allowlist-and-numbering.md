# S01 — Spec correction: dispatch-only pattern + numbering re-check

- **Milestone:** 0.0.4 — quality-feedback (module)
- **Track:** T1 Foundation
- **Size:** XS
- **Depends on:** none — must land first
- **Delivers:** corrects FR-1, FR-3; NFR-6 (ADR + PRD accuracy)
- **Surface:** ADR-0154 + module PRD; no code

## Goal

Two statements in the module's own governance docs are wrong against the shipped
architecture. Every later slice builds to them, so they are corrected before any
code is written.

**1. "Registered in NO profile tool allowlist" is impossible.** The deterministic
dispatch route gates on the profile allowlist itself — a tool absent from the
allowlist returns `policy_blocked` and is unreachable. Building to the current
wording produces a dead tool.

The shipped pattern for "the BFF may dispatch it, a model may never call it"
(used by `toee_agent_experience`, `toee_metrics`, `toee_retention`,
`toee_job_queue`, `toee_integrations`) is **both** of:

- the tool **is** in the profile allowlist, so the dispatch gate passes; **and**
- each `(tool, action)` pair is in the plugin's agent-excluded set, so tool
  registration skips it and it never reaches the model surface.

The governance property ADR-0154 claims — *the AI cannot score itself* — still
holds, and holds for a second independent reason: the copilot draft turn's boot
path carries no acting employee, so a feedback write attempted from it fails
closed on the actor check regardless of registration.

**2. The reserved migration number keeps rotting — stop hardcoding it.** This
module has now lost `0012` → `0016` → `0017` to concurrent landings
(`0012_outbound_send`, then `0016_scripted_eval_turn`, then
`0017_honored_rate_aggregate` — confirmed via `ls hermes-runtime/migrations/`).
Migrations are landing on this branch faster than this module ships, so **the
migration slices (S03, S06) take "the next free number, re-checked immediately
before the migration PR"**, not a fixed value. At the time of writing the next
free number is **`0018`** (S03's `interaction_review`), with `0019` next in
line (S06's `draft_feedback`); treat both as provisional. ADR-0154 already
landed and needs no renumber.

## Approach

- Rewrite the ADR-0154 decision-3 wording from "registered in no allowlist" to
  the allowlist + agent-excluded pattern, keeping the governance claim intact and
  naming the boot-path argument as the load-bearing guarantee.
- Correct the migration number in the PRD (FR-1) and in the design spec's §0
  revision note; state the tool-level (not action-level) allowlist consequence.
- Record in the PRD that allowlisting is **per tool**, so an action's profile
  restriction is enforced by which BFF route exists, not by the allowlist.

## Acceptance — three-layer gate (docs-only carve-out)

- **① Technical:** no code change; repo-wide grep shows no remaining "no profile
  tool allowlist" claim and no remaining `0012` reference for this module. ADR
  and PRD agree with each other on the pattern and the number.
- **② E2E (browser):** carve-out — no behaviour surface.
- **③ Product (PAC):** none; unblocks every later slice.

## Out of scope

- Any tool, migration, or UI code — this slice is the spec correction only.
- Re-numbering ADR-0154 (it landed correctly).
