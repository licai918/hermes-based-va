# S11 — Turn observability: binding_key + slot names + merge-fired

- **Milestone:** 0.0.1 / M1
- **Size:** S
- **Depends on:** S07, S10
- **Delivers:** §6.4 observability
- **Surface:** audit / turn record

## Goal

Any real conversation can be audited after the fact — "did this customer get
*their* memory?" — without logging PII.

## Files (likely)

- Write/merge side: reuse `insert_audit` → `workbench_audit_log`
  (`hermes-runtime/hermes_runtime/datastore/handlers/_common.py`).
- Read/inject side: one compact per-turn note recording the resolved
  `binding_key`, the injected **slot names** (not values), and `merge_fired`.

## Approach

- Record slot **names** only — values never enter logs (PII stays out).
- The write/merge audit already lands in `workbench_audit_log`; add `binding_key`
  as the target and `merge` as an action.

## Acceptance

- For a sample conversation, the record shows the correct `binding_key` and the
  injected slot names; no slot values appear anywhere in logs.
- Satisfies the §6.6 observability checklist item.

## Out of scope

- A UI surface for this (raw record/log is enough for 0.0.1).
