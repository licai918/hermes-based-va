# Durable Postgres job queue (supersedes ADR-0105's Cloud Tasks target)

> ADR number: originally drafted as 0153; renumbered to 0155 because `main`
> landed a different ADR-0153 (provider-neutral SMS tool naming) first, and 0154
> is taken by the manual-scoring-feedback ADR. Both 0153s were authored the same
> day on separate branches; because their filenames differ after the number
> prefix, the merge would have produced two ADR-0153s with no git conflict.

> **Status: Accepted — queue core implemented and cut over** (decided during
> 0.0.4, 2026-07-21). Ships on `feat/0.0.4-land-all`: S01 (FR-7, FR-8, FR-14; PRD
> Track T2), with [migration 0014](../../hermes-runtime/migrations/0014_job_queue.sql)
> and `hermes-runtime/hermes_runtime/job_queue.py`; **S02** (FR-9 turn half, FR-10,
> NFR-1, NFR-2) wired the gateway's fast-ack path to it, added
> `hermes_runtime/turn_worker.py` + the `turn-worker` compose service, and deleted
> `job_dispatch.py`. **Supersedes ADR-0105's transport decision** (Cloud Tasks).
> ADR-0105's *enqueue rule* and *ADR-0107 reload-by-`eventId`* contract are
> unchanged and still hold.
> **S04** (FR-9 background half, FR-11) added
> `hermes_runtime/background_worker.py` + the `background-worker` compose
> service, moved the three background triggers (L6 learning fork, retention
> sweep, knowledge re-ingest) onto the queue, and **runs the schedule tick loop**
> — so the recurring mechanism below is live rather than merely available.
>
> **S05** (FR-13) added the dead-letter operator view + governed **Replay**
> (`datastore/handlers/dead_letter.py`, `job_queue.replay_dead_job`,
> `/admin/dead-letter`). Replay is the ONE operation that deliberately returns a
> row to a claimable status; it is safe because it matches `status = 'dead'`
> only (a dead row already carries `locked_at IS NULL`) and sets `run_at = now()`,
> keeping the fencing invariant below true. Replay safety is **per job type** —
> `job_queue.REPLAY_BLOCKED_JOB_TYPES` blocks `l6_review` until proposal dedupe
> exists.
>
> The queue now has every consumer 0.0.4 planned for it.

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

One `job` table (migration `0014_job_queue.sql`) in the database that is already
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
  so the dead-letter view shows when it last ran. **S05's replay** is the only
  way out of `dead`: `status='queued'`, `attempts=0`, `run_at=now()` on the
  EXISTING row (which is what keeps S03's derived idempotency key identical), and
  only for a job type `REPLAY_BLOCKED_JOB_TYPES` does not name.
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
- **Lease fencing.** `complete()` and `fail()` take the `Job` handed back by
  `claim()`, and only touch a row that is still `running` under that job's exact
  lease (`locked_at`); otherwise they raise `LeaseLost`. Without the fence a
  worker that is *slow, not dead* — its lease reclaimed, the job re-claimed by
  someone else — could mark another worker's in-flight job `succeeded`, knock it
  back to `failed` so a third worker claims it too, or resurrect a `dead` row.
  `locked_at` is sufficient as the credential: every claim writes a fresh
  `now()`, and a row is only re-claimable after a reclaim has pushed it through
  the retry backoff, so two live leases on one row can never share a timestamp.

### 4. Recurring schedules are part of the queue core (no cron)

There is no cron in this repo and none is assumed. A `Schedule(job_type,
interval_seconds)` plus `tick_schedules(schedules)` is the whole mechanism:

    window     = floor(epoch / interval_seconds)
    dedupe_key = f"schedule:{job_type}:{window}"

The key is a **pure function of the clock**, so ticking every second, or ticking
from two workers at once, still produces exactly one job per interval — the unique
index is the coordination, not a lock or a leader election. S04 calls it on the
background worker's poll loop (`background_worker.SCHEDULES`, one entry today:
`retention` every 24 h — sized against the 730/90-DAY windows it enforces);
a duplicate tick is a no-op by construction, and a
worker that was down for one window simply misses that window rather than
replaying a backlog (correct for probes and cadence jobs, which want "run now",
not "catch up").

**Schedules are a list passed by the caller, not a table** (recorded as a
`ponytail:` ceiling): nothing edits them at runtime and there is no UI for them.
Promote to a table the day an operator must change an interval without a deploy.

### 5. Polling, not LISTEN/NOTIFY (NFR-2)

`claim()` is a single-row poll. Workers poll; there is no `LISTEN/NOTIFY`.

- **Poll interval: 250 ms** for the turn worker (`turn_worker.POLL_SECONDS`).
  S01 proposed 1 s; **S02 measured it, and 1 s misses NFR-2**, so S02 took step
  (1) below. **The background worker polls at 5 s**
  (`background_worker.POLL_SECONDS`) — nothing on it has a latency budget, since
  NFR-2 is about a customer waiting on a reply and no customer waits on a
  retention sweep. The only human-facing cost is that an admin trigger takes up
  to one interval to start.

  **Measured (0.0.4 S02) — a one-time snapshot recorded here, NOT a CI gate.**
  Nothing regression-fences these numbers; re-measure if the loop changes.
  Enqueue→claim gap p95 against the docker-compose Postgres, 60 jobs per arm
  arriving uniformly over a two-interval window so arrivals never phase-lock to
  the poll. Baseline is the deleted daemon-thread handoff, 0.4 ms p95:

  | Poll interval | enqueue→claim p95 | vs thread handoff | NFR-2 (< 500 ms) |
  |---|---|---|---|
  | 1.0 s | 981 ms | +981 ms | ✗ |
  | 0.5 s | 495 ms | +495 ms | ✓, zero margin |
  | **0.25 s** | **263 ms** | **+263 ms** | **✓** |

  The gap is ~uniform(0, interval), so p95 ≈ 0.95 × interval — the table confirms
  the arithmetic rather than discovering it. 250 ms costs 4 claims + 4 lease
  sweeps per second per idle worker, both single-row indexed statements, so
  NOTIFY buys nothing until the budget drops near ~100 ms.

  **NFR-1, same run:** webhook ack p95 **4.6 ms → 4.3 ms** (200 signed webhooks
  per arm through the real gateway app onto Postgres, thread handoff vs durable
  INSERT). No regression — enqueue is one INSERT and is not measurably different
  from starting a thread. Also a snapshot, not a gate.
- **Why not NOTIFY now:** it adds a second mechanism (a dedicated listening
  connection per worker, plus its reconnect/missed-notification handling) to save
  at most one poll interval, and a NOTIFY-driven worker *still* needs the poll as
  its correctness floor — a missed notification must not strand a job. Building
  the poll first is the whole queue; NOTIFY is a latency optimization on top.
- **Upgrade path, in order:** (1) shorten the poll interval — free, one constant;
  (2) `LISTEN/NOTIFY` on enqueue with the poll retained as the floor. **S02 took
  step (1)** (1 s → 250 ms) on the measurement above; step (2) remains unbuilt and
  unneeded.

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
- **`LocalDispatchingJobQueue` is deleted by S02, not here.** S01 was additive.
  **Done in S02:** `job_dispatch.py` and `test_job_dispatch.py` are gone, the
  composition root wires `PostgresJobQueue`, and `hermes_runtime/turn_worker.py`
  (docker-compose service `turn-worker`) is the consumer. `PostgresJobQueue.enqueue(payload)`
  kept the one-argument `JobQueue` Protocol shape, so the cutover was a wiring
  change rather than a rewrite, as intended.
- **The durable path requires `TOOL_BACKEND=datastore`, and `build_gateway_app()`
  now enforces it at boot.** Two processes can only share the turn context through
  a shared store, so the in-memory `GatewayStore` cannot produce a working reply
  loop; a gateway on it would ack every webhook and silently never answer. It
  survives for tests, which build `create_app()` directly. Consistent with ADR-0142
  (Postgres is the local substrate), but a real change to what an unset
  `TOOL_BACKEND` does: it is now a boot failure, not a degraded mode.
- **The turn job is enqueued inside the persist transaction** (S02 fix wave 1,
  US3). `PostgresGatewayStore.persist_accepted_inbound` calls
  `job_queue.insert_job(cur, ...)` on its own cursor, so the `agent_turn_context`
  row and the `job` row commit together. There is no `queue` seam on the gateway
  route any more: an enqueue there is by construction a second commit boundary,
  and a crash inside it loses a message the webhook response has already acked —
  with no redelivery to recover it, because the persisted context makes the
  provider's retry a `duplicate` upstream of the enqueue.
- **Everything async gets one substrate.** Turn jobs, the L6 learning fork, the
  retention sweep, knowledge re-ingest, health probes and the honored-rate run all
  become a `type` string on one table, with one retry policy, one dead-letter
  state, and one place to look when something did not happen.
- **A job payload can now be the source of an audit attribution.** S04's
  `retention` job carries the clicking supervisor's `actor_account_id` and
  `retention_sweep.run_sweep` rebuilds a `ToolExecutionContext` from it, which makes
  the queue a SECOND source of `context.user_id` — an invariant
  [ADR-0148](0148-copilot-agent-source-actor-attribution-and-context-only-binding.md)
  had recorded as single-sourced. Safe today and bounded by specific properties;
  **the constraints a future job type must preserve are in that ADR's addendum**,
  not here. Read it before rebuilding a context from any other payload.
- **A dead job is now a visible object.** Today a failed async turn is a log line
  in a dead thread. After S05 it is a row a supervisor can see and replay.
- **Cost:** the queue shares Postgres connections with the request path. At this
  volume that is fine; if worker polling ever contends with turn traffic, the
  first move is a separate pool (the pool is already keyed per DSN), not a
  separate queue product.
- **Constraint — `job` retention is coupled to inbound dedupe (FR-7).** The
  `dedupe_key` unique index is not merely an optimisation: it is the *only*
  guarantee behind inbound-event dedupe. A duplicate webhook is rejected because
  a row with that `dedupe_key` still exists — so the dedupe window is exactly the
  retention window of the `job` table, and `job` has no cleanup story today
  (deliberately: the table is small and `dead` rows are S05's evidence).
  **Therefore: a future retention slice must not delete `job` rows without first
  replacing this guarantee** — either keep terminal rows with a `dedupe_key`
  beyond the provider's replay window, or move dedupe to its own
  `processed_event` table that retention does not touch. Deleting on age alone
  would silently re-open double-processing of inbound events, with no failing
  test to catch it (nothing asserts a dedupe key survives a sweep that does not
  yet exist).

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

`hermes-runtime/tests/test_job_queue.py` — 23 live-Postgres tests (skip-if-no-DB
via the shared `datastore` fixture, throwaway schema per test):

- **enqueue:** queued row with the right defaults; the one-argument
  `AgentJobPayload` shape (the S02 cutover pin); heterogeneous JSONB payloads
  roundtrip; duplicate `dedupe_key` is a no-op returning the same id; jobs without
  a dedupe key are never deduped.
- **claim:** marks `running` with `locked_by`/`locked_at` and `attempts = 1`;
  empty queue returns `None`; a claimed job is not claimed again; future `run_at`
  is skipped; `types=` filtering keeps a turn worker off background jobs, and an
  empty `types=()` allowlist claims *nothing* rather than widening to any type.
- **lease fencing:** the full stale-worker scenario — claim, lease expiry,
  reclaim, re-claim by a second worker — then the stale holder's `complete()`
  and `fail()` both raise `LeaseLost` and leave the row `running` under its new
  owner, who can still complete it; and `complete()` cannot resurrect a `dead`
  row. Both fail against an unfenced `WHERE id = %s`.
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
