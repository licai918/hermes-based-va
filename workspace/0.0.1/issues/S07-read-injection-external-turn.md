# S07 — Read injection — external turn

- **Milestone:** 0.0.1 / M1
- **Size:** M
- **Depends on:** S02, S06
- **Delivers:** FR-1
- **Surface:** external async turn (openrouter)

## Goal

Inject the customer's preference block into the external customer-service turn so
the model sees prior preferences.

## Problem

`run_turn` (`hermes-runtime/hermes_runtime/openrouter.py`) calls
`render_injection(identity, None)` — the memory arg is hard-coded `None`. (The
`pre_llm_call` hook is dead — local vs global PluginManager — so this manual
prepend is the live seam; we extend it, not the hook.)

## Files (likely)

- `hermes-runtime/hermes_runtime/openrouter.py` — `run_turn`.

## Approach

- Compute the binding key from the turn's identity/context (S02 rules): verified →
  `shopify_customer_id`; else `provisional:sms:{E.164}` from `AgentTurnContext
  .from_phone`.
- `memory = store.load_customer_memory(binding_key)` (S06), gated by
  `memory_enabled()` (S05).
- `render_injection(identity, memory)` — `_render_memory` already formats
  `{slot, value}`. No slots → no block (ADR-0113).

## Acceptance

- E2E two-round (S13): state a preference in round 1, re-enter in round 2 → the
  stored value appears in round-2's injected user message (content round-trip R2).
- Unit: verified vs provisional binding selects the right key; empty → no block.

## Out of scope

- Copilot injection (S08); untrusted-data framing of the block (S09).
