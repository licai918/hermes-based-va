# S04 — Identity presets (verified / unknown / ambiguous) + reset / new-conversation controls

- **Milestone:** 0.0.3 — land all of 0.0.3
- **Track:** T2 Conversation Simulator
- **Size:** S
- **Depends on:** S03
- **Delivers:** FR-9 (presets), FR-13 (reset / new-conversation)
- **Surface:** simulator page controls; S02 ingress params

## Goal

FR-9's identity presets — "verified customer (a Shopify-matched number),
unknown caller (fresh number), ambiguous match" — plus FR-13's reset /
new-conversation controls: "fresh simulated identity or clean thread on demand,
so PAC runs are repeatable without cross-contamination" (US2, US6).

## Approach

- Preset picker on the simulator page feeding S02's ingress params: verified =
  a Shopify-matched simulated number; unknown = freshly generated simulated
  number; ambiguous = a number engineered to produce an ambiguous identity match.
- Reset / new-conversation: clean thread or fresh identity on demand; how reset
  is realized (new conversation_id vs cleared state) is implementer's choice,
  as long as no state bleeds between runs.
- **NFR-4:** numbers are always simulated, never a real customer's; simulator
  transcripts are never treated as real customer data.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** vitest: each preset → correct ingress params (matched /
  fresh / ambiguous number); reset yields a fresh conversation with no carried
  state.
- **② E2E (browser):** run a conversation under the verified preset, reset,
  rerun under unknown caller — the agent's identity-dependent behavior visibly
  differs and nothing carries over; screenshots of both runs.
- **③ Product (PAC):** PAC-2 reproducibility — the owner can rerun any scenario
  from a clean state (sign-off at S33).

## Out of scope

- The "link identity" control — **S05**.
- Email identities / channel switching — **S17**/**S18**.
