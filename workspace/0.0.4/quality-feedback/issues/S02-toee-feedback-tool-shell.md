# S02 — `toee_feedback` tool shell: catalog, schemas, allowlists, model exclusion

- **Milestone:** 0.0.4 — quality-feedback (module)
- **Track:** T1 Foundation
- **Size:** S
- **Depends on:** S01
- **Delivers:** FR-3, FR-2 (type half), FR-11, **NFR-3**
- **Surface:** Python tool catalog + param schemas + profile allowlists + plugin
  registration; `packages/shared` TS mirror. No handlers, no migration, no UI.

## Goal

Stand up the shared spine both capture mechanisms extend: the `toee_feedback`
tool declared with its four-action enum, reachable by the BFF over dispatch, and
provably absent from every model's tool surface.

Declaring the shell separately keeps the governance properties (reachability,
model exclusion, TS/Python catalog parity) under test **once**, rather than
re-asserted in each action slice.

## Approach

- Add `toee_feedback` to the Python tool catalog with the fixed action enum:
  `submit_interaction_review`, `record_draft_outcome`, `submit_draft_rating`,
  `list_feedback`.
- Add param schemas for each action (verdict enums, reason-tag arrays, subject
  identifiers).
- Add the tool to the **internal copilot** profile allowlist (the three write
  actions are dispatched from copilot surfaces) and to the **supervisor admin**
  allowlist (`list_feedback`).
- Add all four `(tool, action)` pairs to the plugin's agent-excluded set so
  registration skips them.
- Mirror the tool + action enum into the shared TS catalog, and add a new shared
  module carrying the two **Review Reason Tag** enums (external and internal —
  they are deliberately separate sets) and the verdict types, with the
  house Python-pairing header comment naming the authoritative Python copy.

## Acceptance — three-layer gate

- **① Technical:** allowlist test — the tool resolves for both profiles;
  registration test — no `toee_feedback` action appears in the built model tool
  schemas (grep-proof over the agent-excluded set); catalog parity test — the TS
  and Python action enums match exactly; schema test — a foreign action name is
  rejected by the catalog check.
- **① Technical — eval determinism (NFR-3):** the Launch Eval replay gate stays
  green **unchanged, with no re-recording**. This is the load-bearing check of
  this slice: registering a tool touches the built tool-schema set, which is the
  one thing a deterministic replay is sensitive to. Green proves the agent's
  surface genuinely did not move; a red gate here means the exclusion did not
  hold and the tool leaked to the model. Do **not** re-record to make it pass.
- **② E2E (browser):** carve-out — no behaviour surface yet (no handler).
- **③ Product (PAC):** none directly; feeds PAC-5 (governance).

## Out of scope

- Handlers, migrations, Tool Gate policy, and every UI surface — later slices.
- Any Phase-2 proposal or metrics wiring.
