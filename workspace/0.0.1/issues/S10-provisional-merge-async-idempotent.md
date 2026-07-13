# S10 — Provisional→verified merge (async, idempotent, audited)

- **Milestone:** 0.0.1 / M1
- **Size:** M
- **Depends on:** S02, S04
- **Delivers:** FR-4, correctness R5, RK-5
- **Surface:** async turn + memory/identity handlers

## Goal

Preferences a caller states before verification follow them onto the verified
customer record, per ADR-0112 — without slowing the webhook ack or double-merging.

## Files (likely)

- `hermes-runtime/hermes_runtime/datastore/handlers/memory.py` (or a new
  `merge_provisional` handler) — the merge unit of work.
- The async turn path (`agent_turn_job` / turn runner) — trigger the merge, **not**
  the synchronous webhook route.
- Writes `customer_memory_merge_audit` (table exists; no writer today).

## Approach

- Trigger: on **every verified ingress** (idempotent), probe for provisional slots
  keyed by the caller's channel identity; run only when rows exist.
- Behavior (ADR-0112 verbatim): upsert provisional slots onto the verified key;
  on conflict the **verified value wins** and the provisional value is recorded in
  `customer_memory_merge_audit.details`; delete provisional copies; write the audit
  row (`provisional_key`, `verified_key`, `details`, `mergedAt`).
- Idempotent audit: concurrent inbounds cannot produce two merge rows for the same
  transition.
- Ambiguous match → no merge.

## Acceptance

- Datastore R5 three-state: (a) no-conflict merge, (b) conflict verified-wins +
  audit shadow, (c) ambiguous no-merge; provisional rows deleted after (a)/(b).
- Concurrency: two rapid verified inbounds → exactly one merge audit row.
- Runs off the ack path (asserted: webhook ack latency unaffected).

## Out of scope

- Cross-channel provisional merge (ADR-0112 v1 non-goal).
