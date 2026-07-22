"""0.0.4 S05 (FR-13): the dead-letter operator view + governed Replay.

The queue can now dead-letter (S01), every async trigger rides it (S02/S04), and
outbound sends are idempotent (S03). What was missing was a human: a supervisor
who can SEE stuck work and put one job back on the queue under attribution.

What these tests pin:

1. **Replay resets exactly the three columns S01 specified** and keeps the S01
   fence invariant true -- a ``dead`` row carries ``locked_at IS NULL``, and the
   reset pushes ``run_at`` to ``now()`` before the row becomes claimable again.
2. **Replay-safety is per job type, enforced server-side.** ``l6_review`` is
   BLOCKED (the fork writes a non-deterministic proposal; a re-run duplicates it)
   and the block is a governed ``policy_blocked`` denial, not a UI-only nudge.
3. **Idempotency lineage survives.** A replayed turn re-runs the model and sends
   the customer nothing new, because the job id -- and therefore S03's derived
   key -- is byte-identical to the original.
4. **Attribution comes from session context, never a param** (ADR-0148), and the
   replay writes a Workbench Audit Log row.
5. **The view surfaces more than dead jobs.** S03/S04 leave operator-visible
   ``outbound_send`` states that no dead-letter row captures.

Live-Postgres, skip-if-no-DB via the shared ``datastore`` fixture.
"""

from __future__ import annotations

import pytest
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

from hermes_runtime.job_queue import (
    AGENT_TURN_JOB_TYPE,
    INGEST_JOB_TYPE,
    L6_REVIEW_JOB_TYPE,
    RETENTION_JOB_TYPE,
    PostgresJobQueue,
    replay_blocked_reason,
)

SUPERVISOR = ToolExecutionContext(profile="supervisor_admin", user_id="acct_super")


@pytest.fixture
def queue(datastore):
    _driver, conn, _schema = datastore
    return PostgresJobQueue(connection=conn)


def _dead_job(queue, conn, job_type: str, payload: dict | None = None) -> str:
    """A job driven to ``dead`` through the real claim/fail path (never an INSERT
    of a hand-written status -- the transitions are what S01 guarantees)."""
    job_id = queue.enqueue(payload or {"k": "v"}, job_type=job_type, max_attempts=1)
    job = queue.claim(worker="w", types=(job_type,))
    assert job is not None and job.id == job_id
    queue.fail(job, "boom")
    assert _row(conn, job_id, "status")[0] == "dead"
    return job_id


def _row(conn, job_id: str, *columns: str):
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(columns)} FROM job WHERE id = %s",  # noqa: S608
            (job_id,),
        )
        return cur.fetchone()


def _list(driver, context=SUPERVISOR):
    result = execute_tool(
        tool="toee_job_queue",
        action="list_dead_letters",
        params={},
        context=context,
        driver=driver,
    )
    assert result.ok is True, result.message
    return result.data


def _replay(driver, job_id: str, context=SUPERVISOR):
    return execute_tool(
        tool="toee_job_queue",
        action="replay_job",
        params={"job_id": job_id},
        context=context,
        driver=driver,
    )


def _audit_rows(conn, action: str):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT account_id, profile, target_id, details FROM workbench_audit_log"
            " WHERE action = %s ORDER BY created_at",
            (action,),
        )
        return cur.fetchall()


# --------------------------------------------------------------------------
# the view
# --------------------------------------------------------------------------


def test_a_dead_job_is_listed_with_everything_the_operator_needs(datastore, queue):
    """FR-13's list: type, payload summary, attempts, last_error, timestamps."""
    driver, conn, _schema = datastore
    job_id = _dead_job(queue, conn, RETENTION_JOB_TYPE, {"profile": "internal_copilot"})

    jobs = _list(driver)["jobs"]

    assert len(jobs) == 1
    row = jobs[0]
    assert row["job_id"] == job_id
    assert row["type"] == RETENTION_JOB_TYPE
    assert row["attempts"] == 1 and row["max_attempts"] == 1
    assert row["last_error"] == "boom"
    assert row["payload_summary"] == {"profile": "internal_copilot"}
    assert row["run_at"] and row["created_at"] and row["updated_at"]
    assert row["replayable"] is True and row["replay_blocked_reason"] is None


def test_only_dead_jobs_are_listed(datastore, queue):
    """A queued/running/failed/succeeded job is not stuck work -- the retry
    machinery still owns it, and listing it would drown the rows that need a
    human."""
    driver, conn, _schema = datastore
    dead_id = _dead_job(queue, conn, RETENTION_JOB_TYPE)
    queue.enqueue({}, job_type=RETENTION_JOB_TYPE)  # queued
    running = queue.claim(worker="w", types=(RETENTION_JOB_TYPE,))
    assert running is not None  # running

    assert [j["job_id"] for j in _list(driver)["jobs"]] == [dead_id]


def test_a_dead_turn_job_carries_the_outbound_record_it_left_behind(datastore, queue):
    """S03 built ``idx_outbound_send_job`` for exactly this question: did this job
    already text the customer? It decides whether a replay is a no-op delivery."""
    driver, conn, _schema = datastore
    job_id = _dead_job(queue, conn, AGENT_TURN_JOB_TYPE, {"event_id": "evt-1"})
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO outbound_send (idempotency_key, job_id, event_id,"
            " conversation_id, channel, status, skip_count)"
            " VALUES (%s, %s, 'evt-1', 'conv-1', 'textline_sms', 'sent', 1)",
            (f"{job_id}:evt-1:reply", job_id),
        )
    conn.commit()

    row = _list(driver)["jobs"][0]

    assert row["outbound"]["status"] == "sent"
    assert row["outbound"]["skip_count"] == 1
    assert row["outbound"]["last_error"] is None


def test_the_l6_review_type_is_listed_but_flagged_unreplayable(datastore, queue):
    """The operator must SEE the stuck fork -- being unreplayable is not a reason
    to hide it. The row carries the reason the button is off."""
    driver, conn, _schema = datastore
    _dead_job(queue, conn, L6_REVIEW_JOB_TYPE, {"case_id": "case-1"})

    row = _list(driver)["jobs"][0]

    assert row["type"] == L6_REVIEW_JOB_TYPE
    assert row["replayable"] is False
    assert "dedupe" in row["replay_blocked_reason"]


def test_a_long_payload_value_is_truncated_in_the_summary(datastore, queue):
    """``l6_review``'s payload carries the whole review prompt (draft text
    included). The dead-letter view is a triage list, not a transcript."""
    driver, conn, _schema = datastore
    _dead_job(queue, conn, L6_REVIEW_JOB_TYPE, {"review_prompt": "x" * 500})

    summary = _list(driver)["jobs"][0]["payload_summary"]

    assert len(summary["review_prompt"]) < 200
    assert summary["review_prompt"].endswith("…")


# --------------------------------------------------------------------------
# the outbound buckets (S03/S04 states no dead-letter row captures)
# --------------------------------------------------------------------------


def _outbound(conn, key, *, status, last_error=None, job_id=None, minutes_old=0):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO outbound_send (idempotency_key, job_id, event_id,"
            " conversation_id, channel, status, last_error, created_at, updated_at)"
            " VALUES (%s, %s, %s, 'conv-1', 'textline_sms', %s, %s,"
            "         now() - make_interval(mins => %s),"
            "         now() - make_interval(mins => %s))",
            (key, job_id, key.split(":")[1], status, last_error, minutes_old, minutes_old),
        )
    conn.commit()


def test_a_failed_send_is_an_operator_bucket_even_with_no_dead_job(datastore):
    """S03: ``failed`` means the provider refused and nothing will ever retry --
    a customer is waiting on a reply that will never arrive."""
    driver, conn, _schema = datastore
    _outbound(conn, "job_x:evt-a:reply", status="failed", last_error="502 from provider")

    buckets = _list(driver)["outbound"]

    assert [(b["bucket"], b["slot"]) for b in buckets] == [("send_failed", "reply")]
    assert buckets[0]["last_error"] == "502 from provider"


def test_an_opt_out_confirmation_that_failed_is_surfaced_as_its_own_slot(datastore):
    """S03 fix wave 2: the customer IS opted out but never got the ADR-0016
    confirmation. Same ``failed`` status, no job at all -- the SLOT is how the
    view tells this compliance gap apart from a lost reply."""
    driver, conn, _schema = datastore
    _outbound(conn, "no-job:evt-stop:opt-out", status="failed", last_error="refused")

    row = _list(driver)["outbound"][0]

    assert (row["bucket"], row["slot"], row["job_id"]) == ("send_failed", "opt-out", None)


def test_a_sent_row_carrying_an_error_is_the_missing_mirror_bucket(datastore):
    """S03 fix wave 1, finding 4: the customer HAS the SMS, but the
    ``message_turn`` mirror never landed, so the workbench thread is
    permanently incomplete. Do NOT re-send -- fix the thread row."""
    driver, conn, _schema = datastore
    _outbound(conn, "job_y:evt-b:reply", status="sent", last_error="mirror write failed")

    row = _list(driver)["outbound"][0]

    assert row["bucket"] == "mirror_missing"


def test_a_stale_intent_row_is_surfaced_although_its_job_is_green(datastore, queue):
    """The gap nothing else catches: a process died between recording intent and
    the POST, the re-run skipped quietly, and the JOB SUCCEEDED. No dead-letter
    row exists. Only the age of the ``intent`` row shows it.

    The green job is REAL here (driven through claim -> complete) and the
    assertion covers both halves: the dead list is empty, and the stale send is
    surfaced anyway. Fix wave 1, finding 5 -- the name used to over-claim,
    because no job was created at all."""
    driver, conn, _schema = datastore
    green = queue.enqueue({}, job_type=AGENT_TURN_JOB_TYPE)
    queue.complete(queue.claim(worker="w", types=(AGENT_TURN_JOB_TYPE,)))
    _outbound(
        conn, f"{green}:evt-c:reply", status="intent", minutes_old=120, job_id=green
    )
    _outbound(conn, "job_w:evt-d:reply", status="intent", minutes_old=0)  # in flight

    view = _list(driver)

    assert view["jobs"] == []  # the job really is green -- nothing dead-lettered
    assert [(b["bucket"], b["event_id"]) for b in view["outbound"]] == [
        ("stale_intent", "evt-c")
    ]


def test_a_clean_sent_row_is_not_an_operator_bucket(datastore):
    """The happy path must not fill the view."""
    driver, conn, _schema = datastore
    _outbound(conn, "job_ok:evt-e:reply", status="sent")

    assert _list(driver)["outbound"] == []


# --------------------------------------------------------------------------
# replay
# --------------------------------------------------------------------------


def test_replay_returns_a_dead_job_to_the_queue_with_attempts_reset(datastore, queue):
    """FR-13's core. S01 specified the reset explicitly: dead rows are never
    re-claimed, so replay must set status/attempts/run_at itself."""
    driver, conn, _schema = datastore
    job_id = _dead_job(queue, conn, RETENTION_JOB_TYPE)

    result = _replay(driver, job_id)

    assert result.ok is True
    assert result.data == {"job_id": job_id, "type": RETENTION_JOB_TYPE, "status": "queued"}
    assert _row(conn, job_id, "status", "attempts", "last_error") == ("queued", 0, None)
    # ...and the worker can actually take it again.
    assert queue.claim(worker="w2", types=(RETENTION_JOB_TYPE,)).id == job_id


def test_replay_keeps_the_S01_fence_invariant_true(datastore, queue):
    """S01's invariant: nothing returns a row to a claimable status without
    pushing ``run_at`` forward, and nothing rewrites ``locked_at`` on a running
    row. Replay is the ONE deliberate return-to-claimable in the system; it is
    safe because a ``dead`` row already carries ``locked_at IS NULL``."""
    driver, conn, _schema = datastore
    job_id = _dead_job(queue, conn, RETENTION_JOB_TYPE)
    before = _row(conn, job_id, "run_at", "locked_at", "locked_by")
    assert before[1] is None and before[2] is None  # the premise, verified

    _replay(driver, job_id)

    after = _row(conn, job_id, "run_at", "locked_at", "locked_by")
    assert after[0] > before[0]  # run_at pushed forward
    assert after[1] is None and after[2] is None


def test_replay_never_touches_a_running_job(datastore, queue):
    """A ``running`` row belongs to a live worker's lease. Replaying it would
    rewrite the fence credential and let two workers finish one job."""
    driver, conn, _schema = datastore
    queue.enqueue({}, job_type=RETENTION_JOB_TYPE)
    job = queue.claim(worker="w", types=(RETENTION_JOB_TYPE,))

    result = _replay(driver, job.id)

    assert result.ok is False and result.error_class == "not_found"
    assert _row(conn, job.id, "status", "locked_at")[0] == "running"
    assert _row(conn, job.id, "locked_at")[0] == job.lease


def test_replaying_an_l6_review_job_is_blocked_with_a_clear_message(datastore, queue):
    """The fork WRITES and the model is non-deterministic: a replay produces a
    second, different proposal for one copilot turn.

    Blocked at the HANDLER, not just by a disabled button -- a stale list, a
    curl, or a second tab must all be denied. The operator-readable message is
    carried by the list row's ``replay_blocked_reason`` (asserted above): a
    ``ToolDriverError`` message is sanitized on the way out by design
    (ADR-0136), so the denial itself is a governed ``policy_blocked``.
    """
    driver, conn, _schema = datastore
    job_id = _dead_job(queue, conn, L6_REVIEW_JOB_TYPE)

    result = _replay(driver, job_id)

    assert result.ok is False
    assert result.error_class == "policy_blocked"
    assert _row(conn, job_id, "status")[0] == "dead"
    assert _audit_rows(conn, "job_replayed") == []


@pytest.mark.parametrize(
    "job_type", [AGENT_TURN_JOB_TYPE, RETENTION_JOB_TYPE, INGEST_JOB_TYPE]
)
def test_every_other_job_type_is_replayable(datastore, queue, job_type):
    """The replay-safety table, enforced rather than documented."""
    driver, conn, _schema = datastore
    job_id = _dead_job(queue, conn, job_type)

    assert _replay(driver, job_id).ok is True
    assert _row(conn, job_id, "status")[0] == "queued"


def test_replay_is_refused_while_a_job_of_the_same_type_is_running(datastore, queue):
    """S05 fix wave 1, finding 1. The single-``job_id`` API and the absence of
    bulk replay bound how many rows ONE click touches; neither says anything
    about a job of the same type that is ALREADY RUNNING.

    That gap is reachable without an operator doing anything odd: an ``ingest``
    outliving the 300 s lease is reclaimed mid-run and dead-lettered with
    ``last_error = 'lease expired'`` while it is still embedding, and that row is
    then the most inviting Replay in the table. ``max_attempts=1`` used to be the
    stated protection -- it stopped being one when replay made ``dead``
    claimable again and reset ``attempts`` to 0.
    """
    driver, conn, _schema = datastore
    dead_id = _dead_job(queue, conn, INGEST_JOB_TYPE)
    queue.enqueue({}, job_type=INGEST_JOB_TYPE)
    assert queue.claim(worker="w-live", types=(INGEST_JOB_TYPE,)) is not None

    result = _replay(driver, dead_id)

    assert result.ok is False and result.error_class == "policy_blocked"
    assert _row(conn, dead_id, "status")[0] == "dead"
    assert _audit_rows(conn, "job_replayed") == []
    # ...and the operator is told WHY on the list, because a ToolDriverError
    # message is sanitized on the way out (ADR-0136).
    row = next(j for j in _list(driver)["jobs"] if j["job_id"] == dead_id)
    assert row["replayable"] is False
    assert "running right now" in row["replay_blocked_reason"]


def test_a_running_job_only_blocks_replay_of_its_own_type(datastore, queue):
    """The guard is per type, not a global freeze -- a live agent_turn must not
    stop a supervisor from replaying a stuck retention sweep."""
    driver, conn, _schema = datastore
    dead_id = _dead_job(queue, conn, RETENTION_JOB_TYPE)
    queue.enqueue({}, job_type=AGENT_TURN_JOB_TYPE)
    assert queue.claim(worker="w-live", types=(AGENT_TURN_JOB_TYPE,)) is not None

    assert _replay(driver, dead_id).ok is True
    assert _row(conn, dead_id, "status")[0] == "queued"


def test_the_blocked_set_is_exactly_l6_review():
    """One grep, so a new job type has to make a decision rather than inherit
    'replayable' by silence."""
    assert replay_blocked_reason(L6_REVIEW_JOB_TYPE) is not None
    for job_type in (AGENT_TURN_JOB_TYPE, RETENTION_JOB_TYPE, INGEST_JOB_TYPE):
        assert replay_blocked_reason(job_type) is None


def test_replaying_an_unknown_or_live_job_is_a_governed_not_found(datastore):
    driver, _conn, _schema = datastore

    result = _replay(driver, "job_does_not_exist")

    assert result.ok is False and result.error_class == "not_found"


def test_replay_requires_a_job_id(datastore):
    driver, _conn, _schema = datastore

    result = execute_tool(
        tool="toee_job_queue",
        action="replay_job",
        params={},
        context=SUPERVISOR,
        driver=driver,
    )

    assert result.ok is False


# --------------------------------------------------------------------------
# attribution + audit (ADR-0148 discipline)
# --------------------------------------------------------------------------


def test_the_replay_is_audited_and_attributed_to_the_session_account(datastore, queue):
    driver, conn, _schema = datastore
    job_id = _dead_job(queue, conn, INGEST_JOB_TYPE)

    _replay(driver, job_id)

    rows = _audit_rows(conn, "job_replayed")
    assert len(rows) == 1
    account_id, profile, target_id, details = rows[0]
    assert (account_id, profile, target_id) == ("acct_super", "supervisor_admin", job_id)
    assert details["type"] == INGEST_JOB_TYPE
    assert details["attempts_before"] == 1


def test_a_replay_is_visible_on_the_panel_with_the_account_that_did_it(
    datastore, queue
):
    """S05 fix wave 1, finding 3. FR-13's acceptance gate asks for a VISIBLE
    audit row, but ``job_replayed`` is written with ``target_type='job'`` and
    every workbench audit view is case- or record-scoped, so no UI could show
    it -- PAC-3 needed ``psql``. The list now carries the replay tail, named to
    an account, which is also the only place it can be seen once a successful
    replay removes the job from the dead list."""
    driver, conn, _schema = datastore
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO workbench_account (id, username, password_hash, role)"
            " VALUES ('acct_super', 'super@toee', 'x', 'supervisor')"
        )
    conn.commit()
    job_id = _dead_job(queue, conn, RETENTION_JOB_TYPE)

    _replay(driver, job_id)
    replays = _list(driver)["recent_replays"]

    assert len(replays) == 1
    assert replays[0]["job_id"] == job_id
    assert replays[0]["type"] == RETENTION_JOB_TYPE
    assert replays[0]["account_id"] == "acct_super"
    assert replays[0]["actor_username"] == "super@toee"
    assert replays[0]["created_at"]


def test_replay_is_fail_closed_on_a_missing_actor(datastore, queue):
    """ADR-0148: the acting account comes from session context. With none, the
    replay must not happen AND must not write a NULL-actor audit row."""
    driver, conn, _schema = datastore
    job_id = _dead_job(queue, conn, RETENTION_JOB_TYPE)

    result = _replay(driver, job_id, context=ToolExecutionContext(profile="supervisor_admin"))

    assert result.ok is False and result.error_class == "policy_blocked"
    assert _row(conn, job_id, "status")[0] == "dead"
    assert _audit_rows(conn, "job_replayed") == []


def test_an_actor_supplied_as_a_param_is_ignored(datastore, queue):
    """ADR-0148's whole point (and its S04 addendum: two sources, not three).
    A caller-supplied ``actor_account_id`` must not reach the audit row."""
    driver, conn, _schema = datastore
    job_id = _dead_job(queue, conn, RETENTION_JOB_TYPE)

    execute_tool(
        tool="toee_job_queue",
        action="replay_job",
        params={"job_id": job_id, "actor_account_id": "acct_impostor"},
        context=SUPERVISOR,
        driver=driver,
    )

    assert _audit_rows(conn, "job_replayed")[0][0] == "acct_super"


def test_replay_does_not_edit_the_job_payload(datastore, queue):
    """ADR-0148's S04 addendum bounds the payload-as-attribution-source to
    Python enqueue sites: a replay that RE-RUNS a payload verbatim keeps that
    property; one that EDITS it breaks it."""
    driver, conn, _schema = datastore
    payload = {"profile": "internal_copilot", "actor_account_id": "acct_original"}
    job_id = _dead_job(queue, conn, RETENTION_JOB_TYPE, payload)

    _replay(driver, job_id)

    assert _row(conn, job_id, "payload")[0] == payload


# --------------------------------------------------------------------------
# S03 interplay: a replayed turn texts nobody twice
# --------------------------------------------------------------------------


def test_a_replayed_turn_keeps_its_idempotency_lineage_and_re_sends_nothing(
    datastore, queue
):
    """FR-13's "original idempotency lineage kept", proven end to end.

    Replay resets the EXISTING row, so ``job.id`` -- and therefore S03's derived
    key ``{job_id}:{event_id}:reply`` -- is byte-identical to the original. The
    re-run finds the row, skips the whole delivery, and counts the skip.
    """
    from hermes_runtime.outbound_send import (
        OutboundSendLog,
        deliver_once,
        outbound_idempotency_key,
    )

    driver, conn, _schema = datastore
    job_id = _dead_job(queue, conn, AGENT_TURN_JOB_TYPE, {"event_id": "evt-replay"})
    log = OutboundSendLog(connection=conn)
    sent: list[str] = []
    deliver_once(
        log=log,
        job_id=job_id,
        event_id="evt-replay",
        conversation_id="conv-1",
        channel="textline_sms",
        deliver=lambda: sent.append("first"),
    )
    assert sent == ["first"]

    assert _replay(driver, job_id).ok is True
    replayed = queue.claim(worker="w2", types=(AGENT_TURN_JOB_TYPE,))
    assert replayed.id == job_id  # the SAME row -- the lineage

    deliver_once(
        log=log,
        job_id=replayed.id,
        event_id="evt-replay",
        conversation_id="conv-1",
        channel="textline_sms",
        deliver=lambda: sent.append("second"),
    )

    assert sent == ["first"]  # the customer was not texted twice
    with conn.cursor() as cur:
        cur.execute(
            "SELECT idempotency_key, job_id, skip_count FROM outbound_send"
            " WHERE event_id = 'evt-replay'"
        )
        key, recorded_job, skips = cur.fetchone()
    assert key == outbound_idempotency_key(job_id=job_id, event_id="evt-replay")
    assert recorded_job == job_id and skips == 1
