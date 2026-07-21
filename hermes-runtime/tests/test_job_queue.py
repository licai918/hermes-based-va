"""0.0.4 S01 (FR-7/FR-8): the durable Postgres job queue core.

Live-Postgres tests for the claim/retry/dead-letter/lease semantics that make
async work survive process death (ADR-0153). Skip-if-no-DB via the shared
``datastore`` fixture (a migrated throwaway schema), so these never touch dev
data (ADR-0142 local-first).

Nothing consumes the queue yet -- S02 wires the turn worker, S04 the background
worker (and the schedule tick loop), S05 the dead-letter view.
"""

from __future__ import annotations

import threading

import pytest

from toee_hermes.gateway.agent_turn import AgentJobPayload

from hermes_runtime.datastore.config import database_url
from hermes_runtime.job_queue import PostgresJobQueue, Schedule

try:  # psycopg lives in the hermes-runtime venv (ADR-0142); guard for safety.
    import psycopg
except ImportError:  # pragma: no cover - exercised only without the driver
    psycopg = None  # type: ignore[assignment]


@pytest.fixture
def migrated(datastore):
    """``(conn, schema)`` for a migrated throwaway schema (shared fixture)."""
    _driver, conn, schema = datastore
    return conn, schema


@pytest.fixture
def queue(migrated):
    conn, _schema = migrated
    return PostgresJobQueue(connection=conn)


def _row(conn, job_id: str, *columns: str):
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(columns)} FROM job WHERE id = %s",  # noqa: S608
            (job_id,),
        )
        return cur.fetchone()


def _count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM job")
        return cur.fetchone()[0]


# --------------------------------------------------------------------------
# enqueue
# --------------------------------------------------------------------------


def test_enqueue_inserts_a_queued_job(queue, migrated):
    conn, _ = migrated
    job_id = queue.enqueue({"event_id": "evt_1"}, job_type="agent_turn")

    status, job_type, payload, attempts, max_attempts = _row(
        conn, job_id, "status", "type", "payload", "attempts", "max_attempts"
    )
    assert status == "queued"
    assert job_type == "agent_turn"
    assert payload == {"event_id": "evt_1"}
    assert attempts == 0
    assert max_attempts == 3


def test_enqueue_accepts_the_existing_agent_job_payload_shape(queue, migrated):
    """S02's cutover must be wiring, not a rewrite: ``enqueue(payload)`` still
    takes the one-argument ``AgentJobPayload`` the ``JobQueue`` Protocol uses."""
    conn, _ = migrated
    job_id = queue.enqueue(AgentJobPayload(event_id="evt_9", conversation_id="conv_9"))

    assert _row(conn, job_id, "payload")[0] == {
        "event_id": "evt_9",
        "conversation_id": "conv_9",
    }


def test_heterogeneous_payloads_roundtrip_as_jsonb(queue, migrated):
    """The queue is type-agnostic: no turn-shaped payload assumptions (FR-7)."""
    conn, _ = migrated
    payload = {"kind": "retention", "cutoff_days": 30, "dry_run": False, "keys": [1, 2]}
    job_id = queue.enqueue(payload, job_type="retention_sweep")

    assert _row(conn, job_id, "payload")[0] == payload


def test_duplicate_dedupe_key_is_a_no_op(queue, migrated):
    conn, _ = migrated
    first = queue.enqueue({"event_id": "evt_1"}, dedupe_key="evt_1")
    second = queue.enqueue({"event_id": "evt_1"}, dedupe_key="evt_1")

    assert second == first
    assert _count(conn) == 1


def test_jobs_without_a_dedupe_key_are_never_deduped(queue, migrated):
    conn, _ = migrated
    queue.enqueue({"n": 1})
    queue.enqueue({"n": 2})

    assert _count(conn) == 2


# --------------------------------------------------------------------------
# claim
# --------------------------------------------------------------------------


def test_claim_returns_the_job_and_marks_it_running(queue, migrated):
    conn, _ = migrated
    job_id = queue.enqueue({"event_id": "evt_1"}, job_type="agent_turn")

    job = queue.claim(worker="worker-a")
    assert job is not None
    assert job.id == job_id
    assert job.type == "agent_turn"
    assert job.payload == {"event_id": "evt_1"}
    assert job.attempts == 1

    status, locked_by, locked_at = _row(conn, job_id, "status", "locked_by", "locked_at")
    assert status == "running"
    assert locked_by == "worker-a"
    assert locked_at is not None


def test_claim_returns_none_when_the_queue_is_empty(queue):
    assert queue.claim(worker="worker-a") is None


def test_a_claimed_job_is_not_claimed_again(queue):
    queue.enqueue({"event_id": "evt_1"})

    assert queue.claim(worker="worker-a") is not None
    assert queue.claim(worker="worker-b") is None


def test_claim_skips_jobs_scheduled_for_the_future(queue, migrated):
    conn, _ = migrated
    job_id = queue.enqueue({"event_id": "evt_later"})
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE job SET run_at = now() + interval '1 hour' WHERE id = %s", (job_id,)
        )
    conn.commit()

    assert queue.claim(worker="worker-a") is None


def test_claim_filters_by_job_type(queue):
    """FR-9: the turn worker must never pick up a background job."""
    queue.enqueue({"n": 1}, job_type="retention_sweep")

    assert queue.claim(worker="turn-worker", types=("agent_turn",)) is None
    assert queue.claim(worker="bg-worker", types=("retention_sweep",)) is not None


def test_concurrent_workers_never_double_claim(queue, migrated):
    """FOR UPDATE SKIP LOCKED: every job claimed exactly once under contention."""
    if psycopg is None:  # pragma: no cover - the fixture already skipped
        pytest.skip("psycopg not installed")
    from psycopg import sql

    _conn, schema = migrated
    total, workers = 24, 6
    for n in range(total):
        queue.enqueue({"n": n})

    claimed: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(workers)
    errors: list[Exception] = []

    def drain(worker: str) -> None:
        conn = psycopg.connect(database_url(), connect_timeout=5)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SET search_path TO {}").format(sql.Identifier(schema))
                )
            conn.commit()
            own = PostgresJobQueue(connection=conn)
            barrier.wait(timeout=10)
            while (job := own.claim(worker=worker)) is not None:
                with lock:
                    claimed.append(job.id)
        except Exception as exc:  # surfaced below so a thread never dies silently
            errors.append(exc)
            barrier.abort()
        finally:
            conn.close()

    threads = [
        threading.Thread(target=drain, args=(f"worker-{i}",)) for i in range(workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    assert len(claimed) == total, "a job was claimed twice or lost"
    assert len(set(claimed)) == total


# --------------------------------------------------------------------------
# complete / fail / dead-letter
# --------------------------------------------------------------------------


def test_complete_marks_the_job_succeeded_and_releases_the_lease(queue, migrated):
    conn, _ = migrated
    queue.enqueue({"event_id": "evt_1"})
    job = queue.claim(worker="worker-a")

    queue.complete(job.id)

    status, locked_by, locked_at = _row(conn, job.id, "status", "locked_by", "locked_at")
    assert status == "succeeded"
    assert locked_by is None
    assert locked_at is None
    assert queue.claim(worker="worker-b") is None


def test_fail_retries_with_exponential_backoff(queue, migrated):
    conn, _ = migrated
    queue.enqueue({"event_id": "evt_1"})

    job = queue.claim(worker="worker-a")
    queue.fail(job.id, "boom")
    status, last_error = _row(conn, job.id, "status", "last_error")
    assert status == "failed"
    assert last_error == "boom"
    # attempt 1 -> 2s: due soon, but not yet.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_at > now(), run_at > now() + interval '3 seconds' FROM job"
            " WHERE id = %s",
            (job.id,),
        )
        due_later, beyond_three = cur.fetchone()
    conn.commit()
    assert (due_later, beyond_three) == (True, False)

    # A failed job is retried once its backoff elapses.
    with conn.cursor() as cur:
        cur.execute("UPDATE job SET run_at = now() WHERE id = %s", (job.id,))
    conn.commit()
    retried = queue.claim(worker="worker-a")
    assert retried is not None and retried.attempts == 2

    # attempt 2 -> 4s: strictly longer than attempt 1's backoff.
    queue.fail(retried.id, "boom again")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_at > now() + interval '3 seconds' FROM job WHERE id = %s",
            (job.id,),
        )
        assert cur.fetchone()[0] is True
    conn.commit()


def test_fail_dead_letters_when_attempts_are_exhausted(queue, migrated):
    conn, _ = migrated
    job_id = queue.enqueue({"event_id": "evt_1"}, max_attempts=2)

    for attempt in (1, 2):
        job = queue.claim(worker="worker-a")
        assert job is not None and job.attempts == attempt
        queue.fail(job.id, f"boom {attempt}")
        with conn.cursor() as cur:
            cur.execute("UPDATE job SET run_at = now() WHERE id = %s", (job_id,))
        conn.commit()

    status, attempts, last_error = _row(conn, job_id, "status", "attempts", "last_error")
    assert status == "dead"
    assert attempts == 2
    assert last_error == "boom 2"
    # Dead is terminal: never silently retried.
    assert queue.claim(worker="worker-a") is None


# --------------------------------------------------------------------------
# lease reclaim
# --------------------------------------------------------------------------


def test_expired_lease_is_reclaimed_and_becomes_claimable(queue, migrated):
    """FR-8/NFR-3: a crashed worker's running job is never stranded."""
    conn, _ = migrated
    queue.enqueue({"event_id": "evt_1"})
    job = queue.claim(worker="dead-worker")

    assert queue.reclaim_expired_leases(lease_seconds=3600) == []
    assert queue.reclaim_expired_leases(lease_seconds=0) == [job.id]

    status, locked_by, last_error = _row(conn, job.id, "status", "locked_by", "last_error")
    assert status == "failed"
    assert locked_by is None
    assert last_error == "lease expired"

    # A reclaimed job serves the same backoff as any other failed attempt, so a
    # job that reliably kills its worker cannot hot-loop.
    assert queue.claim(worker="worker-b") is None
    with conn.cursor() as cur:
        cur.execute("UPDATE job SET run_at = now() WHERE id = %s", (job.id,))
    conn.commit()

    reclaimed = queue.claim(worker="worker-b")
    assert reclaimed is not None and reclaimed.id == job.id
    assert reclaimed.attempts == 2


def test_expired_lease_dead_letters_when_attempts_are_exhausted(queue, migrated):
    conn, _ = migrated
    job_id = queue.enqueue({"event_id": "evt_1"}, max_attempts=1)
    queue.claim(worker="dead-worker")

    assert queue.reclaim_expired_leases(lease_seconds=0) == [job_id]
    assert _row(conn, job_id, "status")[0] == "dead"


# --------------------------------------------------------------------------
# recurring schedules (gap-review fix T1 -- no cron exists in this repo)
# --------------------------------------------------------------------------


def test_tick_enqueues_due_schedules_once_per_window(queue, migrated):
    conn, _ = migrated
    schedules = (Schedule(job_type="health_probe", interval_seconds=300),)

    first = queue.tick_schedules(schedules, now_epoch=1_000_000)
    repeat = queue.tick_schedules(schedules, now_epoch=1_000_100)

    assert len(first) == 1
    assert repeat == [], "a duplicate tick in the same window must be a no-op"
    assert _count(conn) == 1

    job_type, dedupe_key, payload = _row(
        conn, first[0], "type", "dedupe_key", "payload"
    )
    assert job_type == "health_probe"
    assert dedupe_key == "schedule:health_probe:3333"
    assert payload == {"schedule_window": 3333, "window_start": 999_900}


def test_tick_enqueues_the_next_window(queue, migrated):
    conn, _ = migrated
    schedules = (Schedule(job_type="health_probe", interval_seconds=300),)

    queue.tick_schedules(schedules, now_epoch=1_000_000)
    later = queue.tick_schedules(schedules, now_epoch=1_000_400)

    assert len(later) == 1
    assert _count(conn) == 2


def test_tick_enqueues_each_schedule_independently(queue, migrated):
    conn, _ = migrated
    schedules = (
        Schedule(job_type="health_probe", interval_seconds=300),
        Schedule(job_type="honored_rate", interval_seconds=86_400),
    )

    assert len(queue.tick_schedules(schedules, now_epoch=1_000_000)) == 2

    with conn.cursor() as cur:
        cur.execute("SELECT type FROM job ORDER BY type")
        assert [row[0] for row in cur.fetchall()] == ["health_probe", "honored_rate"]


def test_scheduled_jobs_are_claimable_like_any_other_job(queue):
    queue.tick_schedules(
        (Schedule(job_type="health_probe", interval_seconds=300),), now_epoch=1_000_000
    )

    job = queue.claim(worker="bg-worker", types=("health_probe",))
    assert job is not None and job.type == "health_probe"
