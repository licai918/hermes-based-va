# S11 — ADR: `copilot_agent` source + actor column + carve-out removal

- **Milestone:** 0.0.2 — memory governance
- **Size:** S
- **Depends on:** S01, S02, S04
- **Delivers:** §5/§9, ADR
- **Surface:** docs (ADR)

## Goal

Record **one** ADR amending ADR-0111 / 0112 / 0114 — the `copilot_agent` source
value, the actor column, and the carve-out removal.

## Problem

0.0.2 changes the write-governance contract (new source value, actor attribution,
removed binding carve-out), but ADR-0111 (write sources) / 0112 (provisional
merge) / 0114 (v1 actions/allowlists) still describe the pre-0.0.2 rules. Without
an amendment the shipped decisions drift from the docs.

## Files (likely)

- new ADR under the ADR directory (amends 0111 / 0112 / 0114).

## Approach

Per PRD §5 / §9; depends on S01/S02/S04 having landed (record what actually
shipped, not the plan):

- One ADR recording: (1) the `copilot_agent` source value + the
  `context.user_id`-presence discriminator invariant (RK-2 — document the UI ⟺
  actor-present rule); (2) the **nullable** actor column (no backfill); (3) the
  `channel_identity_id` carve-out removal → **context-only** binding, unresolvable
  = `policy_blocked`.

## Acceptance

- The ADR is merged, references the three amended ADRs (0111/0112/0114), and
  matches what S01/S02/S04 actually shipped.

## Out of scope

- The code changes themselves — **S01/S02/S04**.
