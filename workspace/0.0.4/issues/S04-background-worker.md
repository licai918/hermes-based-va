# S04 — Background worker + trigger migration (L6 / retention / re-ingest)

- **Milestone:** 0.0.4 — durable substrate
- **Track:** T2 Durable job queue
- **Size:** M
- **Depends on:** S01
- **Delivers:** FR-9 (background half), FR-11
- **Surface:** background-worker process + the three trigger sites; admin re-ingest panel action

## Goal

FR-11 (grilled decision 6): the L6 learning fork, retention sweep, and
knowledge re-ingest are enqueued as typed jobs on the queue, consumed by a
**background worker** separate from the turn worker (grilled decision 9) —
one observable substrate for all async work, and a long ingest can never
delay a customer turn.

## Approach

- Background worker entrypoint claiming `type in (l6_review, retention,
  ingest)`; docker-compose service.
- Trigger migration only — behavior and audit semantics unchanged:
  - L6 post-copilot-turn fork → enqueue `l6_review`.
  - Retention sweep schedule/admin action → enqueue `retention`.
  - Admin corpus "re-ingest" (0.0.3 S11 panel; CLI-display stub) → becomes a
    real enqueue + status readback on the panel.
- Retry/dead-letter semantics inherited from S01 (per-type max_attempts
  tunable; ingest likely 1).

## Acceptance — three-layer gate

- **① Technical:** per-type tests — trigger enqueues, worker executes the
  existing job body, failure retries then dead-letters; isolation test — a
  slow background job never blocks a queued turn job.
- **② E2E (browser):** admin panel re-ingest click → job runs → corpus
  status updates; screenshot.
- **③ Product (PAC):** PAC-4 — owner triggers re-ingest while running a
  simulator turn; the turn completes without added delay.

## Out of scope

- Any change to L6/retention/ingest **behavior** (PRD §6).
- New job types beyond the three named.
