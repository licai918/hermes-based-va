# S01 — Postgres job queue core + queue ADR

- **Milestone:** 0.0.4 — durable substrate
- **Track:** T2 Durable job queue
- **Size:** M
- **Depends on:** none (0.0.3 merged to main)
- **Delivers:** FR-7, FR-8, FR-14
- **Surface:** `hermes-runtime` migration + queue module; no UI

## Goal

FR-7/FR-8: a `job` table in the Toee Business Datastore with
claim/retry/dead-letter/lease semantics, so async work survives process
death. FR-14: the ADR superseding ADR-0105's Cloud Tasks target.

## Approach

- Migration: `job` table — id, type, payload JSONB, status
  (`queued|running|succeeded|failed|dead`), attempts, max_attempts (default
  3), run_at, locked_at/locked_by, last_error, dedupe_key (unique, nullable),
  created_at/updated_at.
- Queue module implementing the existing `JobQueue` Protocol
  (`gateway_store.py`): enqueue (INSERT, dedupe-key no-op on conflict), claim
  via `FOR UPDATE SKIP LOCKED`, complete/fail, exponential backoff on retry,
  `dead` on exhaustion, lease reclaim of stale `running` jobs.
- **Recurring schedules (gap-review fix T1 — no cron exists anywhere in the
  repo):** a schedule table/config (job type + interval) and a tick routine
  that enqueues due periodic jobs with a deterministic `(type, window)`
  dedupe key — duplicate ticks no-op on the unique index. The tick loop runs
  inside the background worker (S04); this slice delivers the mechanism +
  tests. Consumers: S16 probes, S22 honored-rate, S04 retention cadence.
- No consumer cutover here — S02/S04 wire the workers. `LocalDispatchingJobQueue`
  still runs production until S02.
- **Queue ADR** ships in this slice: Postgres queue chosen; ADR-0105 Cloud
  Tasks target formally superseded; ADR-0142 local-first alignment;
  lease/retry/dead-letter semantics recorded.

## Acceptance — three-layer gate

- **① Technical:** DB-backed tests for enqueue/claim/retry/dead/lease-reclaim
  and dedupe no-op; concurrent-claim test proves no double-claim.
- **② E2E (browser):** n/a yet (no consumer) — CI run page green as evidence.
- **③ Product (PAC):** infrastructure slice — feeds PAC-2 via S02.

## Out of scope

- Worker processes — **S02/S04**. Outbound idempotency — **S03**.
- Dead-letter UI — **S05**. LISTEN/NOTIFY latency tuning — only if S02's
  NFR-2 gate demands it (record either way in the ADR).
