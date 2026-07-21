"""0.0.4 S04 (FR-9 background half, FR-11): the background worker + the three
migrated triggers.

The L6 learning fork, the retention sweep and the knowledge re-ingest are now
typed jobs on the durable queue, consumed by a process that is deliberately NOT
the turn worker. What these tests pin:

1. **Isolation both ways (FR-9).** This worker never claims an ``agent_turn``
   job, and a slow background job never delays one -- the second half proven
   against the real turn worker's ``run_once``, not by inspection.
2. **The recurring tick exists at all.** There is no cron in this repo; the
   schedule tick on this loop is what gives retention a cadence, and ticking
   twice in a window is a no-op.
3. **Retry/dead-letter per type.** ``ingest`` and ``l6_review`` get ONE attempt
   (both are non-idempotent writers); ``retention`` gets the default 3.

Live-Postgres, skip-if-no-DB via the shared ``datastore`` fixture.
"""

from __future__ import annotations

import logging

import pytest

from hermes_runtime.background_worker import (
    BACKGROUND_JOB_TYPES,
    INGEST_CORPUS_PATH_ENV,
    POLL_SECONDS,
    SCHEDULES,
    _error_backoff_seconds,
    _run_ingest,
    job_bodies,
    poll_forever,
    run_once,
)
from hermes_runtime.job_queue import (
    AGENT_TURN_JOB_TYPE,
    INGEST_JOB_TYPE,
    L6_REVIEW_JOB_TYPE,
    RETENTION_JOB_TYPE,
    PostgresJobQueue,
    Schedule,
)


@pytest.fixture
def queue(datastore):
    _driver, conn, _schema = datastore
    return PostgresJobQueue(connection=conn)


def _row(conn, job_id: str, *columns: str):
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(columns)} FROM job WHERE id = %s",  # noqa: S608
            (job_id,),
        )
        return cur.fetchone()


def _recording_bodies(seen: list, *, raises: dict | None = None) -> dict:
    """A body map that records each payload it is handed (and can explode)."""
    raises = raises or {}

    def make(job_type):
        def body(payload):
            seen.append((job_type, dict(payload)))
            if job_type in raises:
                raise raises[job_type]

        return body

    return {t: make(t) for t in BACKGROUND_JOB_TYPES}


# --------------------------------------------------------------------------
# claim + dispatch
# --------------------------------------------------------------------------


@pytest.mark.parametrize("job_type", BACKGROUND_JOB_TYPES)
def test_run_once_claims_each_background_type_and_completes_it(datastore, queue, job_type):
    _driver, conn, _schema = datastore
    job_id = queue.enqueue({"marker": job_type}, job_type=job_type)
    seen: list = []

    job = run_once(queue=queue, bodies=_recording_bodies(seen), worker="bg-1", schedules=())

    assert job is not None and job.id == job_id
    assert seen == [(job_type, {"marker": job_type})]
    assert _row(conn, job_id, "status", "locked_by") == ("succeeded", None)


def test_run_once_returns_none_when_nothing_is_due(queue):
    assert run_once(queue=queue, bodies=job_bodies(), worker="bg-1", schedules=()) is None


def test_the_background_worker_never_claims_a_turn_job(datastore, queue):
    """FR-9 isolation, this worker's half: ``types=`` omits ``agent_turn``, so a
    customer's turn job is invisible here no matter how long it has waited."""
    _driver, conn, _schema = datastore
    turn_id = queue.enqueue(
        {"event_id": "evt-1", "conversation_id": "conv-1"}, job_type=AGENT_TURN_JOB_TYPE
    )
    seen: list = []

    assert run_once(queue=queue, bodies=_recording_bodies(seen), worker="bg-1", schedules=()) is None
    assert seen == []
    assert _row(conn, turn_id, "status") == ("queued",)
    assert AGENT_TURN_JOB_TYPE not in BACKGROUND_JOB_TYPES


def test_a_long_background_job_never_delays_a_queued_turn(datastore, queue):
    """FR-9, the half that matters to a customer (PAC-4): with a background job
    already claimed and 'running' (an ingest that will take minutes), the turn
    worker's very next poll still claims and runs the turn.

    Two workers, not one loop -- which is the whole reason there are two
    processes. This drives the REAL ``turn_worker.run_once``, so deleting the
    ``types=`` allowlist from either worker breaks it.
    """
    from hermes_runtime.postgres_gateway_store import PostgresGatewayStore
    from hermes_runtime.turn_worker import run_once as turn_run_once
    from toee_hermes.gateway.ingress import SessionIdentitySnapshot
    from toee_hermes.gateway.normalize import InboundChannelEvent
    from toee_hermes.gateway.pipeline import InboundDecision

    _driver, conn, _schema = datastore
    store = PostgresGatewayStore(connection=conn)

    # A long ingest, claimed first and still in flight.
    ingest_id = queue.enqueue({"slow": True}, job_type=INGEST_JOB_TYPE)
    in_flight = queue.claim(worker="bg-1", types=BACKGROUND_JOB_TYPES)
    assert in_flight is not None and in_flight.id == ingest_id

    # ...then a customer message arrives.
    event = InboundChannelEvent(
        channel="textline_sms",
        provider="textline",
        event_id="evt-iso",
        conversation_id="conv-iso",
        from_phone="+15559876543",
        body="is this in stock?",
        received_at="2026-01-01T00:00:00Z",
        raw_event_type="message.created",
        media_urls=None,
    )
    store.persist_accepted_inbound(
        InboundDecision(
            status=200,
            action="enqueue",
            stage="accept",
            event=event,
            snapshot=SessionIdentitySnapshot(
                outcome="unmatched_caller", resolved_at="2026-01-01T00:00:00Z"
            ),
        )
    )

    sent: list = []

    def _runner(context, inbound_body, job_id=None):
        sent.append((context.conversation_id, inbound_body))

    turn_job = turn_run_once(queue=queue, store=store, turn_runner=_runner, worker="turn-1")

    assert turn_job is not None
    assert sent == [("conv-iso", "is this in stock?")]
    # The ingest is untouched and still held by its own worker.
    assert _row(conn, ingest_id, "status", "locked_by") == ("running", "bg-1")


def test_an_unknown_job_type_is_failed_not_silently_completed(datastore, queue):
    _driver, conn, _schema = datastore
    job_id = queue.enqueue({}, job_type=RETENTION_JOB_TYPE)

    job = run_once(queue=queue, bodies={}, worker="bg-1", schedules=())

    assert job is not None and job.id == job_id
    status, last_error = _row(conn, job_id, "status", "last_error")
    assert status == "failed"
    assert RETENTION_JOB_TYPE in last_error


# --------------------------------------------------------------------------
# failure / retry / dead-letter, per type
# --------------------------------------------------------------------------


def test_a_raising_job_is_failed_with_its_error_and_retried(datastore, queue):
    _driver, conn, _schema = datastore
    job_id = queue.enqueue({}, job_type=RETENTION_JOB_TYPE)
    seen: list = []
    bodies = _recording_bodies(seen, raises={RETENTION_JOB_TYPE: RuntimeError("pg went away")})

    run_once(queue=queue, bodies=bodies, worker="bg-1", schedules=())

    status, attempts, last_error = _row(conn, job_id, "status", "attempts", "last_error")
    assert (status, attempts) == ("failed", 1)  # retry-pending, not dead
    assert "pg went away" in last_error


def test_a_failing_job_dead_letters_after_its_attempts_are_spent(datastore, queue):
    _driver, conn, _schema = datastore
    job_id = queue.enqueue({}, job_type=RETENTION_JOB_TYPE)
    bodies = _recording_bodies([], raises={RETENTION_JOB_TYPE: RuntimeError("still broken")})

    for _attempt in range(3):
        with conn.cursor() as cur:  # serve the backoff; it is S01-tested
            cur.execute("UPDATE job SET run_at = now() WHERE id = %s", (job_id,))
        conn.commit()
        run_once(queue=queue, bodies=bodies, worker="bg-1", schedules=())

    status, attempts = _row(conn, job_id, "status", "attempts")
    assert (status, attempts) == ("dead", 3)


def test_a_failing_ingest_dead_letters_on_its_FIRST_attempt(datastore, queue):
    """Per-type ``max_attempts``: ingest TRUNCATEs and re-embeds the whole corpus,
    so three automatic attempts would wipe and reload it three times over one
    transient failure. One attempt, then S05's governed replay."""
    _driver, conn, _schema = datastore
    job_id = queue.enqueue({}, job_type=INGEST_JOB_TYPE, max_attempts=1)
    bodies = _recording_bodies([], raises={INGEST_JOB_TYPE: RuntimeError("fastembed OOM")})

    run_once(queue=queue, bodies=bodies, worker="bg-1", schedules=())

    status, attempts = _row(conn, job_id, "status", "attempts")
    assert (status, attempts) == ("dead", 1)


def test_a_worker_that_died_mid_job_has_its_lease_reclaimed(datastore, queue):
    """NFR-3 for background work. The sweep is at the top of ``run_once``, so this
    drill exercises production code -- delete it and this test fails."""
    _driver, conn, _schema = datastore
    job_id = queue.enqueue({}, job_type=RETENTION_JOB_TYPE)
    claimed = queue.claim(worker="bg-dead", types=BACKGROUND_JOB_TYPES)
    assert claimed is not None

    # Worker A never completed. Worker B polls with a zero-second lease policy.
    run_once(queue=queue, bodies=job_bodies(), worker="bg-2", schedules=(), lease_seconds=0)

    status, last_error = _row(conn, job_id, "status", "last_error")
    assert (status, last_error) == ("failed", "lease expired")


# --------------------------------------------------------------------------
# schedules -- the whole reason recurring work exists (FR-8)
# --------------------------------------------------------------------------


def test_the_shipped_schedule_is_a_daily_retention_sweep():
    assert [(s.job_type, s.interval_seconds) for s in SCHEDULES] == [
        (RETENTION_JOB_TYPE, 86400)
    ]


def test_the_tick_on_the_poll_loop_enqueues_the_schedule_and_the_worker_runs_it(
    datastore, queue
):
    """Retention was manual-only before this slice. One poll of this worker, with
    no operator anywhere, both creates the sweep job and executes it."""
    _driver, conn, _schema = datastore
    seen: list = []

    job = run_once(queue=queue, bodies=_recording_bodies(seen), worker="bg-1")

    assert job is not None and job.type == RETENTION_JOB_TYPE
    assert [t for t, _payload in seen] == [RETENTION_JOB_TYPE]
    assert _row(conn, job.id, "status") == ("succeeded",)


def test_ticking_twice_in_the_same_window_creates_exactly_one_job(datastore, queue):
    _driver, conn, _schema = datastore
    schedules = (Schedule(job_type=RETENTION_JOB_TYPE, interval_seconds=86400),)

    run_once(queue=queue, bodies=_recording_bodies([]), worker="bg-1", schedules=schedules)
    run_once(queue=queue, bodies=_recording_bodies([]), worker="bg-2", schedules=schedules)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM job WHERE type = %s", (RETENTION_JOB_TYPE,))
        assert cur.fetchone()[0] == 1


# --------------------------------------------------------------------------
# the job bodies' wiring
# --------------------------------------------------------------------------


def test_every_background_type_has_a_body():
    assert set(job_bodies()) == set(BACKGROUND_JOB_TYPES)


def test_an_ingest_with_no_corpus_artifact_fails_with_an_actionable_error(monkeypatch):
    monkeypatch.delenv(INGEST_CORPUS_PATH_ENV, raising=False)

    with pytest.raises(RuntimeError, match=INGEST_CORPUS_PATH_ENV):
        _run_ingest({})


def test_the_l6_body_runs_the_fork_over_the_payloads_prompt(monkeypatch):
    """The migrated L6 trigger: the copilot turn builds the prompt and enqueues;
    the worker's body feeds that exact prompt to the unchanged fork."""
    import hermes_runtime.copilot_turn as copilot_mod

    seen: dict = {}

    def _fake_pass(*, user_message, **_kwargs):
        seen["user_message"] = user_message
        return []

    monkeypatch.setattr(copilot_mod, "_run_review_pass", _fake_pass)

    job_bodies()[L6_REVIEW_JOB_TYPE](
        {"case_id": "case_x", "review_prompt": "Review the copilot turn for case_x."}
    )

    assert seen["user_message"] == "Review the copilot turn for case_x."


# --------------------------------------------------------------------------
# the migrated triggers, end to end -- behavior and audit unchanged (FR-11)
# --------------------------------------------------------------------------


def _aged_verified_slot(conn) -> str:
    """A ``customer_memory_slot`` well past its 730-day verified window."""
    import uuid
    from datetime import datetime, timedelta, timezone

    slot_id = f"mem_{uuid.uuid4().hex}"
    stale = datetime.now(timezone.utc) - timedelta(days=800)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO customer_memory_slot
                (id, binding_key, binding_kind, slot_name, slot_value, source,
                 created_at, updated_at, last_interaction_at)
            VALUES (%s, 'gid://shopify/Customer/1', 'verified',
                    'contact_time_preference', 'x', 'customer_explicit', %s, %s, %s)
            """,
            (slot_id, stale, stale, stale),
        )
    conn.commit()
    return slot_id


def _audit_rows(conn, action: str):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT account_id, profile, details FROM workbench_audit_log"
            " WHERE action = %s",
            (action,),
        )
        return cur.fetchall()


def test_the_admin_button_enqueues_a_retention_job_the_worker_sweeps_with_the_SAME_audit(
    datastore, queue, monkeypatch
):
    """FR-11's core claim for retention: only the substrate moved.

    The panel's governed ``dispatchWrite`` used to run the DELETE inline. It now
    enqueues -- and the sweep the worker runs still deletes exactly the aged rows
    and still writes ONE ``retention_sweep`` audit row attributed to the
    supervisor who clicked, because the actor rides in the job payload.
    """
    import hermes_runtime.retention_sweep as retention_mod
    from toee_hermes.execute import execute_tool
    from toee_hermes.tool_gate import ToolExecutionContext

    driver, conn, _schema = datastore
    slot_id = _aged_verified_slot(conn)

    trigger = execute_tool(
        tool="toee_retention",
        action="enqueue_retention_sweep",
        params={},
        context=ToolExecutionContext(profile="internal_copilot", user_id="acct_super"),
        driver=driver,
    )
    assert trigger.ok is True and trigger.data["status"] == "queued"
    # Nothing swept yet -- the button no longer does the work.
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM customer_memory_slot WHERE id = %s", (slot_id,))
        assert cur.fetchone()[0] == 1
    assert _audit_rows(conn, "retention_sweep") == []

    # The worker's poll runs the unchanged sweep body.
    monkeypatch.setattr(retention_mod, "PostgresDriver", lambda *a, **k: driver)
    job = run_once(queue=queue, bodies=job_bodies(), worker="bg-1", schedules=())

    assert job is not None and job.type == RETENTION_JOB_TYPE
    assert _row(conn, job.id, "status") == ("succeeded",)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM customer_memory_slot WHERE id = %s", (slot_id,))
        assert cur.fetchone()[0] == 0
    rows = _audit_rows(conn, "retention_sweep")
    assert len(rows) == 1
    account_id, profile, details = rows[0]
    assert (account_id, profile) == ("acct_super", "internal_copilot")
    assert details["counts"] == {"verified": 1, "provisional": 0}


def test_a_scheduled_sweep_audits_unattended_exactly_like_the_cli_run(
    datastore, queue, monkeypatch
):
    """The cadence half. A tick-created job has no actor, which is the same
    "no attributed actor for an unattended run" the CLI entrypoint always had."""
    import hermes_runtime.retention_sweep as retention_mod

    driver, conn, _schema = datastore
    _aged_verified_slot(conn)
    monkeypatch.setattr(retention_mod, "PostgresDriver", lambda *a, **k: driver)

    job = run_once(queue=queue, bodies=job_bodies(), worker="bg-1")  # real SCHEDULES

    assert job is not None and job.type == RETENTION_JOB_TYPE
    rows = _audit_rows(conn, "retention_sweep")
    assert len(rows) == 1
    account_id, profile, _details = rows[0]
    assert account_id is None and profile == "internal_copilot"


def test_the_reingest_panel_action_queues_a_real_ingest_job_and_reads_it_back(datastore):
    """FR-11: 0.0.3 S11 shipped a panel that printed a CLI command. It now
    enqueues a real job, audits the trigger, and the panel's status readback
    (``get_corpus_status``'s ``last_ingest_job``) finds it."""
    from hermes_runtime.datastore.handlers.knowledge import _last_ingest_job
    from toee_hermes.execute import execute_tool
    from toee_hermes.tool_gate import ToolExecutionContext

    driver, conn, _schema = datastore

    result = execute_tool(
        tool="toee_knowledge_ops",
        action="enqueue_corpus_reingest",
        params={},
        context=ToolExecutionContext(profile="supervisor_admin", user_id="acct_admin"),
        driver=driver,
    )

    assert result.ok is True
    job_id = result.data["job_id"]
    assert result.data["status"] == "queued"
    # ONE attempt: a retry would TRUNCATE and re-embed the whole corpus again.
    assert _row(conn, job_id, "type", "status", "max_attempts") == (
        INGEST_JOB_TYPE,
        "queued",
        1,
    )
    assert [(a, p) for a, p, _d in _audit_rows(conn, "corpus_reingest_queued")] == [
        ("acct_admin", "supervisor_admin")
    ]
    readback = _last_ingest_job(conn)
    assert readback["job_id"] == job_id and readback["status"] == "queued"


def test_the_reingest_action_is_fail_closed_on_a_missing_actor(datastore):
    """A governed WRITE that TRUNCATEs the corpus never lands unattributed."""
    from toee_hermes.execute import execute_tool
    from toee_hermes.tool_gate import ToolExecutionContext

    driver, conn, _schema = datastore

    result = execute_tool(
        tool="toee_knowledge_ops",
        action="enqueue_corpus_reingest",
        params={},
        context=ToolExecutionContext(profile="supervisor_admin"),
        driver=driver,
    )

    assert result.ok is False
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM job WHERE type = %s", (INGEST_JOB_TYPE,))
        assert cur.fetchone()[0] == 0


def test_neither_enqueue_action_is_reachable_from_a_live_agents_tool_loop():
    """Both triggers are admin-only: a model that could reach them would have
    'delete customer data' / 'wipe the corpus' one indirection away."""
    from toee_hermes.plugin import _AGENT_EXCLUDED_ACTIONS

    assert ("toee_retention", "enqueue_retention_sweep") in _AGENT_EXCLUDED_ACTIONS
    assert ("toee_knowledge_ops", "enqueue_corpus_reingest") in _AGENT_EXCLUDED_ACTIONS


# --------------------------------------------------------------------------
# the loop shell
# --------------------------------------------------------------------------


class _FlakyQueue:
    """Fails ``reclaim_expired_leases`` on the listed sweep numbers."""

    def __init__(self, fail_on: set[int]) -> None:
        self.fail_on = fail_on
        self.sweeps = 0

    def reclaim_expired_leases(self, *, lease_seconds=None):
        self.sweeps += 1
        if self.sweeps in self.fail_on:
            raise RuntimeError("connection refused")
        return []

    def tick_schedules(self, schedules, **_kwargs):
        return []

    def claim(self, *, worker, types=None):
        return None


def test_a_database_blip_backs_off_and_is_logged_instead_of_killing_the_worker(caplog):
    flaky = _FlakyQueue(fail_on={1, 2, 3, 5})
    slept: list = []

    def _sleep(seconds):
        slept.append(seconds)

    with caplog.at_level(logging.ERROR):
        poll_forever(
            queue=flaky,
            bodies={},
            worker="bg-1",
            sleep=_sleep,
            should_stop=lambda: flaky.sweeps >= 5,
        )

    # 3 failures escalate, the 4th poll succeeds and RESETS, the 5th is back to 1x.
    assert slept == [
        POLL_SECONDS * 2,
        POLL_SECONDS * 4,
        POLL_SECONDS * 8,
        POLL_SECONDS,
        POLL_SECONDS * 2,
    ]
    assert len([r for r in caplog.records if r.levelno >= logging.ERROR]) == 4


def test_the_error_backoff_is_bounded():
    assert _error_backoff_seconds(50) == 60.0
