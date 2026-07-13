# S01 — Thread channel identity (E.164) into ingress context

- **Milestone:** 0.0.1 / M1
- **Size:** S
- **Depends on:** —
- **Delivers:** FR-5 prerequisite, RK-3
- **Surface:** ingress / plugin context

## Goal

Make the caller's channel identity (SMS phone, E.164) available on the
`ToolExecutionContext` so Customer Memory binding is derived from
ingress-controlled context, never from a model-supplied tool parameter.

## Problem

`snapshot_as_identity_dict` (`hermes/toee_hermes/gateway/ingress.py`) emits only
`{outcome, resolved_at, shopify_customer_id?, shopify_customer_ids?, company_name?}`.
For an unmatched/ambiguous caller there is **no phone in context**, so provisional
binding today can only come from a model param (the RK-3 vulnerability).

## Interface (pin these exact keys — S02 consumes them)

The turn identity dict gains two keys: `"channel": "sms"` and
`"channel_identity": "<E.164>"` (normalized). They ride `context.identity`, never
a tool-schema param (model-invisible).

## Files

- `hermes-runtime/hermes_runtime/openrouter.py` — in `run_turn`, the phone is NOT
  in the snapshot; enrich at the turn boundary. After
  `identity = snapshot_as_identity_dict(snapshot)`, add
  `identity["channel"] = "sms"` and
  `identity["channel_identity"] = normalize_e164(context.from_phone)` (the
  `AgentTurnContext` has `from_phone`). Pass this enriched `identity` to BOTH
  `render_injection(...)` and `boot_profile(..., identity=identity)` — the latter
  is what lands it on `ToolExecutionContext.identity` (via
  `_make_context_provider`), where the memory handler reads it.
- Handle `snapshot is None` (unmatched with no snapshot): still build an identity
  dict carrying channel + channel_identity so provisional binding works.
- reuse `normalize_e164` from `hermes/toee_hermes/gateway/normalize.py`.

## Approach

- Keep `snapshot_as_identity_dict` unchanged (it only has the snapshot); do the
  enrichment where `from_phone` is in scope (the turn boundary).
- Copilot's channel-identity enrichment is a separate seam handled in S08.

## Acceptance

- Unit: a resolved snapshot (verified and unmatched) produces a context whose
  identity carries the E.164 channel identity.
- No new tool-schema parameter is exposed to the model.

## Out of scope

- Binding-key construction and fail-closed logic (S02).
