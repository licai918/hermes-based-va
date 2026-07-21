# S05 — Dead-letter workbench view + governed Replay

- **Milestone:** 0.0.4 — durable substrate
- **Track:** T2 Durable job queue
- **Size:** M
- **Depends on:** S03 (replay safety), S04 (all job types exist)
- **Delivers:** FR-13
- **Surface:** workbench route (supervisor/admin) + admin-API read/replay endpoints

## Goal

FR-13 (grilled decision 7): dead jobs are visible in the workbench — type,
payload summary, attempts, last_error, timestamps — and a **Replay** action
re-enqueues one job, attributed to the acting account and written to the
Workbench Audit Log. US5/US6.

## Approach

- Admin-API: list dead jobs + replay-one (attempts reset, original
  idempotency lineage kept so S03 still suppresses duplicate sends).
- Workbench: dead-letter page under the admin/supervisor route group
  (ADR-0093 role-gating), list + per-row Replay with confirm.
- Replay attribution: acting account from session context (ADR-0148
  discipline — never from request params); audit row written.
- No bulk replay (PRD default).

## Acceptance — three-layer gate

- **① Technical:** BFF + handler tests (list, replay, role-gating, audit
  row); replayed turn job with prior send POSTs nothing (S03 interplay).
- **② E2E (browser):** force a dead job → visible in the view → Replay →
  job succeeds → audit row visible; screenshots.
- **③ Product (PAC):** PAC-3 — owner forces retry exhaustion, sees the dead
  letter, replays as supervisor, checks the audit attribution.

## Out of scope

- Bulk replay, queue dashboards/metrics (PRD §6).
