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

## Files (likely)

- `hermes/toee_hermes/gateway/ingress.py` — add the channel identity to the
  identity dict (e.g. `channel: "sms"`, `channel_identity: "+1..."`).
- `hermes/toee_hermes/plugin/__init__.py` — `_make_context_provider` /
  `ToolExecutionContext` carries it through (already closes over `identity`).
- `hermes/toee_hermes/tool_gate.py` (`ToolExecutionContext`) — confirm the field
  exists or add it.

## Approach

- Carry the normalized E.164 the ingress pipeline already has (`from_phone`) into
  the identity dict under a stable key.
- Keep it model-invisible: it rides `context.identity`, not a tool schema param.

## Acceptance

- Unit: a resolved snapshot (verified and unmatched) produces a context whose
  identity carries the E.164 channel identity.
- No new tool-schema parameter is exposed to the model.

## Out of scope

- Binding-key construction and fail-closed logic (S02).
