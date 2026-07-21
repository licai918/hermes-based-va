"""Durable Postgres job queue (0.0.4 S01, FR-7/FR-8, ADR-0153).

Replaces ADR-0105's never-built Cloud Tasks target with the database that is
already the system of record (ADR-0140/0142): one ``job`` table, claimed with
``FOR UPDATE SKIP LOCKED``, retried with exponential backoff, dead-lettered on
exhaustion, and reclaimed after a lease timeout when a worker dies mid-job.

The queue is **type-agnostic**: the payload is JSONB and nothing here imports
turn logic, so the same table carries inbound turn jobs, the L6 learning fork,
retention sweeps, knowledge re-ingest, health probes and the honored-rate run.

Nothing consumes it yet. S02 cuts the gateway over to :class:`PostgresJobQueue`
(``enqueue`` keeps the one-argument shape of the existing ``JobQueue`` Protocol
in ``gateway_store.py``, so that is a wiring change), S04 runs the background
worker and the :meth:`PostgresJobQueue.tick_schedules` loop, S05 surfaces
``dead`` rows for governed replay.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from typing import Any, Iterator, Mapping, Optional, Sequence

import psycopg
from psycopg.types.json import Jsonb

from .datastore.config import database_url
from .datastore.handlers._common import new_id
from .datastore.pool import get_database_pool

# PRD default (FR-8), overridable per enqueue for a job type that warrants it.
DEFAULT_MAX_ATTEMPTS = 3

# How long a claim is valid before another worker may reclaim the job. Long
# enough to cover a slow model turn, short enough that a killed worker's job is
# picked up within a minute (NFR-3).
DEFAULT_LEASE_SECONDS = 300

# Retry backoff: run_at = now() + BASE ** attempts seconds (2s, 4s, 8s ...).
# ponytail: fixed base, no jitter -- at SMS volume a handful of retries never
# thunder. Add jitter if a fan-out job type ever retries in lockstep.
_BACKOFF_BASE = 2

_LEASE_EXPIRED_ERROR = "lease expired"

# Claimable statuses: never ran, or failed and waiting out its backoff.
_CLAIMABLE_SQL = "('queued', 'failed')"

# The default job type, so ``enqueue(payload)`` stays call-compatible with the
# existing one-argument ``JobQueue`` Protocol. A string, not an import: the
# queue still knows nothing about turns.
AGENT_TURN_JOB_TYPE = "agent_turn"


@dataclass(frozen=True)
class Job:
    """A claimed unit of work. ``attempts`` includes the current attempt."""

    id: str
    type: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


@dataclass(frozen=True)
class Schedule:
    """A recurring job type (gap-review fix T1).

    No cron exists in this repo and none is assumed: the background worker (S04)
    calls :meth:`PostgresJobQueue.tick_schedules` on its poll loop, and the
    deterministic ``(type, window)`` dedupe key makes every extra tick a no-op.
    ponytail: schedules are a plain list passed by the caller, not a table --
    nothing edits them at runtime and there is no UI for them. Promote to a table
    the day an operator needs to change an interval without a deploy.
    """

    job_type: str
    interval_seconds: int


def _as_payload(payload: Any) -> dict[str, Any]:
    """Accept a dataclass (e.g. ``AgentJobPayload``) or a plain mapping."""
    if is_dataclass(payload) and not isinstance(payload, type):
        return asdict(payload)
    if isinstance(payload, Mapping):
        return dict(payload)
    raise TypeError(
        "Job payload must be a dataclass instance or a mapping; "
        f"got {type(payload).__name__}."
    )


class PostgresJobQueue:
    """The ``job`` table as a queue.

    Two connection modes, mirroring :class:`~hermes_runtime.datastore.driver.PostgresDriver`:
    ``connection=`` (caller-owned, tests/single-process dev) or ``dsn=`` (a
    connection from the process-level pool per operation).

    Every method is its own unit of work and commits before returning, so a
    claim is visible to other workers immediately and a crash between operations
    can never lose a job.
    """

    def __init__(
        self,
        *,
        connection: Optional[psycopg.Connection] = None,
        dsn: Optional[str] = None,
    ) -> None:
        if connection is None and dsn is None:
            dsn = database_url()
        self._connection = connection
        self._dsn = dsn

    @contextmanager
    def _connect(self) -> Iterator[psycopg.Connection]:
        if self._connection is not None:
            yield self._connection
        else:
            with get_database_pool(self._dsn).connection() as conn:
                yield conn

    @contextmanager
    def _unit_of_work(self) -> Iterator[psycopg.Cursor]:
        with self._connect() as conn:
            try:
                with conn.cursor() as cur:
                    yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    # -- enqueue -----------------------------------------------------------

    def enqueue(
        self,
        payload: Any,
        *,
        job_type: str = AGENT_TURN_JOB_TYPE,
        dedupe_key: Optional[str] = None,
        run_at: Optional[datetime] = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> str:
        """Insert one job; return its id. A duplicate ``dedupe_key`` is a no-op
        and returns the id of the job already queued (FR-7)."""
        return self._insert(
            payload,
            job_type=job_type,
            dedupe_key=dedupe_key,
            run_at=run_at,
            max_attempts=max_attempts,
        )[0]

    def _insert(
        self,
        payload: Any,
        *,
        job_type: str,
        dedupe_key: Optional[str],
        run_at: Optional[datetime],
        max_attempts: int,
    ) -> tuple[str, bool]:
        """``(job_id, created)`` -- ``created`` is False on a dedupe no-op."""
        job_id = new_id("job")
        with self._unit_of_work() as cur:
            cur.execute(
                """
                INSERT INTO job (id, type, payload, dedupe_key, run_at, max_attempts)
                VALUES (%s, %s, %s, %s, COALESCE(%s, now()), %s)
                ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING
                RETURNING id
                """,
                (
                    job_id,
                    job_type,
                    Jsonb(_as_payload(payload)),
                    dedupe_key,
                    run_at,
                    max_attempts,
                ),
            )
            row = cur.fetchone()
            if row is not None:
                return row[0], True
            # Dedupe no-op: hand back the job that already owns the key.
            cur.execute("SELECT id FROM job WHERE dedupe_key = %s", (dedupe_key,))
            return cur.fetchone()[0], False

    # -- claim / complete / fail -------------------------------------------

    def claim(
        self,
        *,
        worker: str,
        types: Optional[Sequence[str]] = None,
    ) -> Optional[Job]:
        """Atomically take the oldest due job (optionally of ``types``).

        ``FOR UPDATE SKIP LOCKED`` is what lets N workers claim concurrently
        without ever handing the same row to two of them (FR-8). The lease is
        just ``locked_at``; its timeout is the reclaimer's policy
        (:meth:`reclaim_expired_leases`), not a per-row column.

        ponytail: one row per call, polled by the worker loop -- no
        LISTEN/NOTIFY. See ADR-0153: the poll interval is the latency knob and
        NOTIFY is the named upgrade path if S02's NFR-2 measurement demands it.
        """
        type_filter = list(types) if types else None
        with self._unit_of_work() as cur:
            cur.execute(
                f"""
                UPDATE job SET
                    status = 'running',
                    attempts = attempts + 1,
                    locked_at = now(),
                    locked_by = %s,
                    updated_at = now()
                WHERE id = (
                    SELECT id FROM job
                    WHERE status IN {_CLAIMABLE_SQL}
                      AND run_at <= now()
                      AND (%s::text[] IS NULL OR type = ANY(%s::text[]))
                    ORDER BY run_at, created_at
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, type, payload, attempts, max_attempts
                """,
                (worker, type_filter, type_filter),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return Job(id=row[0], type=row[1], payload=row[2], attempts=row[3], max_attempts=row[4])

    def complete(self, job_id: str) -> None:
        """Mark a claimed job succeeded and release its lease."""
        with self._unit_of_work() as cur:
            cur.execute(
                """
                UPDATE job SET
                    status = 'succeeded',
                    locked_at = NULL,
                    locked_by = NULL,
                    last_error = NULL,
                    updated_at = now()
                WHERE id = %s
                """,
                (job_id,),
            )

    def fail(self, job_id: str, error: str) -> None:
        """Record a failed attempt: retry after backoff, or dead-letter.

        A job whose attempts are exhausted moves to ``dead`` and stays there --
        never silently dropped, never silently retried (FR-8). S05 surfaces dead
        rows for governed replay.
        """
        self._release(job_id_clause="id = %s", params=(error, job_id))

    def reclaim_expired_leases(
        self, *, lease_seconds: int = DEFAULT_LEASE_SECONDS
    ) -> list[str]:
        """Return ``running`` jobs whose lease expired to the queue (or ``dead``).

        This is how a worker killed mid-job stops stranding it (NFR-3). Reclaim
        reuses the same attempt accounting as :meth:`fail`, so a job that keeps
        killing its worker dead-letters instead of looping forever.
        """
        return self._release(
            job_id_clause=(
                "status = 'running' AND locked_at < now() - make_interval(secs => %s)"
            ),
            params=(_LEASE_EXPIRED_ERROR, lease_seconds),
        )

    def _release(self, *, job_id_clause: str, params: tuple[Any, ...]) -> list[str]:
        """Shared fail/reclaim transition: dead on exhaustion, else retry-pending.

        ``run_at`` only moves for a retry -- a dead row keeps its last schedule so
        the dead-letter view shows when it last ran.
        """
        with self._unit_of_work() as cur:
            cur.execute(
                f"""
                UPDATE job SET
                    status = CASE
                        WHEN attempts >= max_attempts THEN 'dead' ELSE 'failed'
                    END,
                    run_at = CASE
                        WHEN attempts >= max_attempts THEN run_at
                        ELSE now() + interval '1 second' * power({_BACKOFF_BASE}, attempts)
                    END,
                    locked_at = NULL,
                    locked_by = NULL,
                    last_error = %s,
                    updated_at = now()
                WHERE {job_id_clause}
                RETURNING id
                """,
                params,
            )
            return [row[0] for row in cur.fetchall()]

    # -- recurring schedules -----------------------------------------------

    def tick_schedules(
        self, schedules: Sequence[Schedule], *, now_epoch: Optional[float] = None
    ) -> list[str]:
        """Enqueue every schedule whose current window has no job yet.

        The window is ``floor(epoch / interval)``, so the dedupe key
        ``schedule:<type>:<window>`` is a pure function of the clock: ticking
        twice a second, or from two workers at once, still produces exactly one
        job per interval -- the unique index is the coordination, not a lock.

        Returns the ids of jobs actually created (empty when every schedule's
        window is already covered).
        """
        moment = time.time() if now_epoch is None else now_epoch
        created: list[str] = []
        for schedule in schedules:
            window = int(moment // schedule.interval_seconds)
            job_id, is_new = self._insert(
                {
                    "schedule_window": window,
                    "window_start": window * schedule.interval_seconds,
                },
                job_type=schedule.job_type,
                dedupe_key=f"schedule:{schedule.job_type}:{window}",
                run_at=None,
                max_attempts=DEFAULT_MAX_ATTEMPTS,
            )
            if is_new:
                created.append(job_id)
        return created
