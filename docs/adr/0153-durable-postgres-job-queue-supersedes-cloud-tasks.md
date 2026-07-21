# Durable Postgres job queue (supersedes ADR-0105's Cloud Tasks target)

> **Status: Accepted — queue core implemented** (decided during 0.0.4, 2026-07-21).
> Ships on `feat/0.0.4-land-all`: S01 (FR-7, FR-8, FR-14; PRD Track T2), with
> [migration 0011](../../hermes-runtime/migrations/0011_job_queue.sql) and
> `hermes-runtime/hermes_runtime/job_queue.py`. **Supersedes ADR-0105's transport
> decision** (Cloud Tasks). ADR-0105's *enqueue rule* and *ADR-0107 reload-by-
> `eventId`* contract are unchanged and still hold.
>
> Consumers land in later slices: S02 (turn worker cutover), S04 (background
> worker + schedule tick loop), S05 (dead-letter view + governed replay).

## Context

ADR-0103 requires the Textline webhook to ack fast and hand the turn off
out-of-band. ADR-0105 named **Google Cloud Tasks** as that handoff, with
`LocalDispatchingJobQueue` (`job_dispatch.py`) as the "local substrate until then".

Cloud Tasks was never built, and two things have since made it the wrong target:

1. **The local substrate became production.** `gateway_composition.py` wires
   `LocalDispatchingJobQueue` in *every* composition, so the real async path is a
   daemon thread with no durability: a crash mid-turn loses the customer's
   message with no record it ever existed. There is no retry, no visibility into
   a failed turn, and no way to replay one.
2. **ADR-0142 reversed the substrate posture.** Local-first is the decided build
   order; Cloud SQL and Cloud Run are deferred. ADR-0105's target contradicts it:
   a Cloud Tasks queue cannot be stood up, tested, or crash-proven locally, which
   would leave the durability story untestable exactly where the code runs today.

Meanwhile the amount of work that needs a queue grew well past inbound turns: the
L6 learning fork, the retention sweep, knowledge re-ingest, scheduled health
probes (FR-24), and the honored-rate judge run (FR-31) all need durable
out-of-band execution. And **no cron exists anywhere in this repo, and none will
be added** — several of those are periodic, so whatever queue we choose has to
answer "what runs this every N minutes" itself.

## Decision

### 1. The queue is a Postgres table in the Toee Business Datastore

One `job` table (migration `0011_job_queue.sql`) in the database that is already
the system of record (ADR-0140), claimed with `FOR UPDATE SKIP LOCKED`.

Rationale: it is **zero new infrastructure**. Postgres is already provisioned,
already backed up, already in docker-compose, already the thing local dev and CI
stand up. A job enqueue joins the same transaction discipline as every other
write, the whole durability story is testable against live Postgres on a laptop
(ADR-0142), and the same migrations target Cloud SQL unchanged if the deferred
cloud slice ever lands. At this system's volume (SMS + email customer service),
Postgres-as-queue is not a compromise — `SKIP LOCKED` is the standard mechanism
and it is correct under real contention (proven by test, see Verification).

### 2. One type-agnostic table, not one table per job kind

`job` carries `type TEXT` + `payload JSONB`. `job_queue.py` imports no turn logic
and has no turn-shaped columns, so a new job type is a new string, never a
migration. The turn worker and the background worker are separated by the
`types=` filter on claim (FR-9: a slow background job can never queue ahead of a
turn job), not by separate tables.

### 3. Lease / retry / dead-letter semantics

Status machine:

```
queued ──claim──> running ──complete──> succeeded
                     │
                     ├──fail (attempts < max)──> failed   (retry pending, run_at = backoff)
                     ├──fail (attempts >= max)─> dead     (terminal)
                     └──lease expiry──────────> failed | dead  (same accounting)
```

- **Claim** takes the oldest due row (`status IN ('queued','failed') AND run_at <=
  now()`), increments `attempts`, sets `locked_at`/`locked_by`, all in one
  statement. `FOR UPDATE SKIP LOCKED` means N workers claim concurrently and no
  row is ever handed to two of them.
- **`failed` is the retry-pending state**, not a terminal one. It keeps
  `last_error` visible while the job waits out its backoff, which is what lets the
  S05 view distinguish "never ran" from "failed twice and retrying".
- **Backoff** is `run_at = now() + 2^attempts` seconds (2s, 4s, 8s …). No jitter:
  at this volume a handful of retries never thunder. Named upgrade path in the
  module's `ponytail:` comment.
- **`max_attempts` defaults to 3** (PRD default), per-enqueue overridable for a
  job type that warrants it.
- **Dead is terminal.** An exhausted job moves to `dead` and is never claimed
  again — never silently dropped, never silently retried. It keeps its `run_at`
  so the dead-letter view shows when it last ran. S05 owns replay.
- **Lease reclaim.** The lease is `locked_at`; its timeout is the *reclaimer's*
  policy (`reclaim_expired_leases(lease_seconds=...)`, default 300s), not a
  per-row column — one policy per worker pool is enough, and it can be changed
  without touching in-flight rows. A reclaimed job runs through the **same**
  attempt accounting as an explicit failure, so a job that reliably kills its
  worker dead-letters instead of hot-looping forever (this is NFR-3: kill a worker
  mid-turn and the message is still processed).
- **Dedupe.** A partial unique index on `dedupe_key WHERE dedupe_key IS NOT NULL`;
  `enqueue` is `ON CONFLICT DO NOTHING` and returns the existing job's id. This
  preserves the gateway's existing inbound-event dedupe semantics (FR-7) and is
  the mechanism the schedule tick rides.

### 4. Recurring schedules are part of the queue core (no cron)

There is no cron in this repo and none is assumed. A `Schedule(job_type,
interval_seconds)` plus `tick_schedules(schedules)` is the whole mechanism:

    window     = floor(epoch / interval_seconds)
    dedupe_key = f"schedule:{job_type}:{window}"

The key is a **pure function of the clock**, so ticking every second, or ticking
from two workers at once, still produces exactly one job per interval — the unique
index is the coordination, not a lock or a leader election. S04 calls it on the
background worker's poll loop; a duplicate tick is a no-op by construction, and a
worker that was down for one window simply misses that window rather than
replaying a backlog (correct for probes and cadence jobs, which want "run now",
not "catch up").

**Schedules are a list passed by the caller, not a table** (recorded as a
`ponytail:` ceiling): nothing edits them at runtime and there is no UI for them.
Promote to a table the day an operator must change an interval without a deploy.

### 5. Polling, not LISTEN/NOTIFY (NFR-2)

`claim()` is a single-row poll. Workers poll; there is no `LISTEN/NOTIFY`.

- **Poll interval: 1 second** for the turn worker (S02 sets it), which puts the
  claim-latency contribution at ≤ 1 s worst case and ~0.5 s average — inside
  NFR-2's < 500 ms p95 budget only if the enqueue-to-claim gap is measured p95,
  which is exactly what S02 measures. The background worker can poll far more
  slowly (S04's call).
- **Why not NOTIFY now:** it adds a second mechanism (a dedicated listening
  connection per worker, plus its reconnect/missed-notification handling) to save
  at most one poll interval, and a NOTIFY-driven worker *still* needs the poll as
  its correctness floor — a missed notification must not strand a job. Building
  the poll first is the whole queue; NOTIFY is a latency optimization on top.
- **Upgrade path, in order:** (1) shorten the poll interval — free, one constant;
  (2) `LISTEN/NOTIFY` on enqueue with the poll retained as the floor. **S02 owns
  the decision**: it measures NFR-2 against the current thread handoff and records
  the number. If a 1 s poll misses the budget, take (1) first.

### 6. Alignment with ADR-0142 (local-first)

This is the point. The durable queue runs on the docker-compose Postgres that
already exists, so crash-recovery, retry, and dead-lettering are provable on a
laptop and in CI — no GCP credentials, no deferred-cloud gap in the durability
story. Migration `0011` is raw SQL like every other migration and targets Cloud
SQL unchanged if the cloud slice lands. Nothing in this decision assumes or
requires a managed service.

## Consequences

- **ADR-0105's transport is superseded.** Cloud Tasks is not the queue and the
  `POST /internal/jobs/agent-turn` route stops being the async execution seam once
  S02 lands; the turn worker claims from the table and calls the same shared
  `execute_agent_turn_job`. ADR-0105's *enqueue rule* (identity keys only, no PII
  body — `eventId` + `conversationId`) and ADR-0107's reload-by-`eventId` contract
  are unchanged: the JSONB payload carries the same minimal identity keys, and
  memory remains the source of truth, not the payload.
- **`LocalDispatchingJobQueue` is deleted by S02, not here.** S01 is additive:
  nothing consumes the queue yet, production still runs the daemon thread, and the
  existing `JobQueue` Protocol is untouched (only its docstring, which still named
  Cloud Tasks). `PostgresJobQueue.enqueue(payload)` keeps that one-argument shape
  deliberately, so the cutover is a wiring change rather than a rewrite.
- **Everything async gets one substrate.** Turn jobs, the L6 learning fork, the
  retention sweep, knowledge re-ingest, health probes and the honored-rate run all
  become a `type` string on one table, with one retry policy, one dead-letter
  state, and one place to look when something did not happen.
- **A dead job is now a visible object.** Today a failed async turn is a log line
  in a dead thread. After S05 it is a row a supervisor can see and replay.
- **Cost:** the queue shares Postgres connections with the request path. At this
  volume that is fine; if worker polling ever contends with turn traffic, the
  first move is a separate pool (the pool is already keyed per DSN), not a
  separate queue product.

## Considered options

- **Build Cloud Tasks as ADR-0105 planned (rejected).** Contradicts ADR-0142,
  cannot be tested locally, and provisions cloud infrastructure for a system that
  does not yet run in the cloud. Reconsider only if the deferred cloud slice lands
  *and* Postgres-as-queue measurably fails.
- **Redis / RQ / Celery (rejected).** A new dependency and a new service to run,
  back up, and monitor — for a queue whose entire volume fits in one Postgres
  table. Also splits durability across two stores: a job enqueued in Redis and a
  turn persisted in Postgres cannot commit together, which is precisely the
  crash window we are closing.
- **Keep the in-process thread and add retries (rejected).** Retries in a process
  that just crashed are not retries. The requirement is surviving process death;
  only an external store can do that.
- **`SELECT ... FOR UPDATE` without `SKIP LOCKED` (rejected).** Correct but
  serializing: every worker queues behind the first one on the same row, so N
  workers give roughly the throughput of one.
- **A separate `job_schedule` table with a `next_run_at` cursor (rejected).**
  A mutable cursor needs a lock or a leader to advance safely, and it can drift.
  The `floor(epoch/interval)` window key needs neither: it is stateless,
  idempotent by construction, and its correctness rests on the unique index the
  table already has for inbound dedupe.
- **`LISTEN/NOTIFY` from day one (rejected for now).** See §5 — it is an
  optimization over a poll loop that must exist anyway, and S02's measurement is
  what should trigger it, not a guess.

## Verification

`hermes-runtime/tests/test_job_queue.py` — 20 live-Postgres tests (skip-if-no-DB
via the shared `datastore` fixture, throwaway schema per test):

- **enqueue:** queued row with the right defaults; the one-argument
  `AgentJobPayload` shape (the S02 cutover pin); heterogeneous JSONB payloads
  roundtrip; duplicate `dedupe_key` is a no-op returning the same id; jobs without
  a dedupe key are never deduped.
- **claim:** marks `running` with `locked_by`/`locked_at` and `attempts = 1`;
  empty queue returns `None`; a claimed job is not claimed again; future `run_at`
  is skipped; `types=` filtering keeps a turn worker off background jobs.
- **contention:** `test_concurrent_workers_never_double_claim` — 6 threads on 6
  connections drain 24 jobs behind a barrier; every job claimed exactly once.
  Mutation-checked: deleting `FOR UPDATE SKIP LOCKED` from the claim makes it fail
  (73 claims for 24 jobs).
- **complete/fail/dead:** succeeded releases the lease; retry backoff grows
  between attempt 1 (2s) and attempt 2 (4s) with `last_error` recorded;
  exhaustion moves to `dead` and `dead` is never claimed again.
- **lease reclaim:** an unexpired lease is left alone, an expired one returns the
  job to `failed` with `last_error = 'lease expired'` and it is claimable again
  after its backoff; an expired lease on an attempts-exhausted job dead-letters.
- **schedules:** a second tick inside the same window is a no-op (one row); the
  next window enqueues again; multiple schedules tick independently; a scheduled
  job is claimable like any other.
