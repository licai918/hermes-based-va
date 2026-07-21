# S14 — Structured proposal envelope: draft turn emits `proposals[]` → agent-turn API → BFF

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T3 Propose→confirm
- **Size:** M
- **Depends on:** S13
- **Delivers:** FR-15
- **Surface:** draft turn output contract; agent-turn API; BFF payload to the workbench

## Goal

FR-15: "structured proposal envelope: the draft turn emits `proposals[]` (slot,
value, evidence-turn) alongside `draft`; carried through the agent-turn API and
BFF to the workbench." Proposals are payload only — nothing persists (US15).

## Approach

- Extend the draft-turn output with `proposals[]` (slot, value, evidence-turn)
  alongside `draft`.
- Carry the envelope unmodified through the agent-turn API → BFF → workbench
  payload.
- Proposals are model-suggested but **inert**: no write path touches them here;
  acceptance, attribution, and `source` stay framework-side (S15 routes Accept
  through the existing governed dispatch write).
- Envelope stays minimal per FR-15; anything beyond slot/value/evidence-turn is
  not in scope.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** unit: a draft turn over a conversation with an inferable
  preference emits well-formed `proposals[]`; no datastore write occurs.
  Vitest BFF: the envelope passes through to the workbench payload intact.
- **② E2E (browser):** drive a copilot conversation; the BFF response visibly
  carries `proposals[]` (browser devtools/network screenshot) — panel rendering
  is S15's.
- **③ Product (PAC):** feeds PAC-3 (owner-visible once S15 renders the
  proposals).

## Out of scope

- Rendering + Accept/Dismiss + audit records — **S15**.
- Proposal history on the supervisor view — **S16**.
