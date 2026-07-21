# S10 — Knowledge on both turn surfaces (external + copilot draft), grounded-chunks discipline

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T1 Knowledge layer L5
- **Size:** S
- **Depends on:** S09
- **Delivers:** FR-5
- **Surface:** external turn profile + copilot draft turn profile; prompt-side grounding guidance

## Goal

FR-5: "injection on both surfaces: the external turn and the copilot draft turn
can call the tool and ground replies on retrieved chunks (in-turn = retrieved
chunks, never synthesis)." US8/US9/US18: grounded answers with the source
cited; honest "don't have that" when retrieval finds nothing.

## Approach

- Add the S09 driver/tool to both turn profiles (external + copilot draft),
  behind `knowledge_enabled()`.
- Grounded-chunks discipline: replies ground on the retrieved chunks with
  title+url provenance; in-turn content is retrieved chunks, never synthesis;
  `found=false` → honest miss, no fabrication.
- Prompt-side citation guidance within the existing profile structure —
  wording is implementer's choice.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** turn-level tests: a policy question triggers the tool and
  the reply grounds on returned chunks; the not-found case produces no
  fabricated answer; eval replay stays green (recording sessions force mock
  backends per the 0.0.2 SECURITY discipline).
- **② E2E (browser):** simulator (S03): as an unknown caller, ask a
  policy/brand question → grounded, cited reply; ask an out-of-corpus question
  → honest "don't have that"; in the copilot workbench, the draft shows the
  same grounding; screenshots of all three.
- **③ Product (PAC):** PAC-1 — the owner runs both legs in the simulator
  (sign-off at S33).

## Out of scope

- Corpus quality / recall tuning — **S12**/**S32**.
- Admin corpus panel — **S11**.
