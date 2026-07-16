# S03 — Copilot draft-persona write-discipline guard

- **Milestone:** 0.0.2 — memory governance
- **Size:** S
- **Depends on:** none
- **Delivers:** FR-1, RK-1
- **Surface:** Copilot draft persona

## Goal

Instruct the Copilot draft agent to record a preference **only when the customer
explicitly stated a durable one in this case's conversation** — never inferred —
mirroring the proven external persona rule.

## Problem

The Copilot `_SYSTEM_MESSAGES` (`hermes-runtime/hermes_runtime/copilot_turn.py:81-108`,
4 channels sms/email/internal_note/chat) say **nothing** about memory writes. The
external persona already carries the rule (`hermes/toee_hermes/persona.py:99-103`:
"ONLY when the customer explicitly asks… NEVER save a preference you merely
inferred"), but the draft path — which can now persist autonomously (S20) — has
no such discipline.

## Files (likely)

- `hermes-runtime/hermes_runtime/copilot_turn.py` — `_SYSTEM_MESSAGES` (:81-108).
- Reference rule: `hermes/toee_hermes/persona.py:99-103`.
- `copilot_turn` persona unit assert.

## Approach

Per FR-1 (RK-1 — mirror the already-proven rule, not a new invention):

- Add the write-discipline rule to each of the 4 channel personas, adapted to
  "…only when the customer explicitly stated a durable preference **in this
  case's conversation** — never inferred from tone, history, or a single order."
- The draft agent **keeps** the tool — no propose→confirm (option D is 0.0.3).
  Soft guard (model behaviour), backed by S07's mechanical eval.

## Acceptance

- Unit (§6.3 FR-1 persona seam): each channel persona string carries the
  no-inferred rule.
- FR-1's eval leg — the copilot no-inferred scenario — is **S07** (it also proves
  this guard holds under regression, R4).

## Out of scope

- The eval that regression-guards this rule — **S07**.
- `source` labelling / actor — **S01/S02**.
