-- 0011_job_queue
-- Durable Postgres job queue (0.0.4 S01, FR-7/FR-8, ADR-0153 -- supersedes
-- ADR-0105's Cloud Tasks target). One table backs ALL async work: inbound turn
-- jobs, the L6 learning fork, retention sweeps, knowledge re-ingest, health
-- probes, the honored-rate judge run. The payload is JSONB and the queue is
-- type-agnostic on purpose -- no turn-shaped columns -- so a new job type is a
-- new `type` string, never a migration.
--
-- Status machine: queued -> running -> succeeded
--                         \-> failed (retry pending, run_at = backoff)
--                         \-> dead   (attempts exhausted; never silently dropped)
-- `failed` is the retry-pending state, so a claim also picks up a due `failed`
-- row while `last_error` stays visible for the S05 dead-letter view.
CREATE TABLE job (
    id           TEXT PRIMARY KEY,
    type         TEXT NOT NULL,
    payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
    status       TEXT NOT NULL DEFAULT 'queued',
    attempts     INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    run_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at    TIMESTAMPTZ,
    locked_by    TEXT,
    last_error   TEXT,
    dedupe_key   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT job_status_check CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'dead')
    )
);

-- Dedupe (FR-7): re-enqueueing an already-known unit of work is a no-op. Also
-- what makes a duplicate schedule tick harmless -- the tick derives a
-- deterministic `schedule:<type>:<window>` key, so two ticks in one window
-- collide here instead of double-running the periodic job. Partial so the vast
-- majority of jobs (no dedupe key) are unconstrained.
CREATE UNIQUE INDEX idx_job_dedupe_key ON job (dedupe_key) WHERE dedupe_key IS NOT NULL;

-- The claim path: due, claimable rows in run order.
-- ponytail: leading on (run_at, created_at) without `type`, so a type-filtered
-- claim (FR-9) walks rows in run order and discards the non-matching ones. Fine
-- while the whole table is a handful of types at SMS volume. Ceiling: a large
-- backlog of one type makes every other worker's claim scan past it. Upgrade
-- path: recreate as (type, run_at, created_at) -- same partial WHERE, index-only
-- seek per type; a plain CREATE/DROP INDEX migration, no table rewrite.
CREATE INDEX idx_job_claim ON job (run_at, created_at)
    WHERE status IN ('queued', 'failed');

-- The lease-reclaim sweep: running rows whose lease may have expired.
CREATE INDEX idx_job_lease ON job (locked_at) WHERE status = 'running';
