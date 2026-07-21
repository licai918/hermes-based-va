"""0.0.4 S02 (FR-9/FR-10, NFR-3): the turn worker consumes the durable queue.

The gateway's fast-ack path now enqueues an ``agent_turn`` job into Postgres and
this worker claims it, runs the *same* shared ``execute_agent_turn_job`` the
in-process dispatcher used to run, and completes it.

What is new -- and what these tests exist for -- is that the turn now survives
the worker. A process killed mid-turn leaves a claimed row, not a dead thread,
and the next worker's sweep reclaims it and finishes the customer's message
(NFR-3 first half). ``test_a_job_whose_worker_died_mid_turn_...`` is that drill:
delete the reclaim sweep from ``run_once`` and it fails, because the row stays
``running`` and is never claimed again.

Live-Postgres, skip-if-no-DB via the shared ``datastore`` fixture (a migrated
throwaway schema), so these never touch dev data (ADR-0142 local-first).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

import pytest
from starlette.testclient import TestClient

from toee_hermes.gateway.agent_turn import AgentJobPayload, AgentTurnContext
from toee_hermes.gateway.ingress import SessionIdentitySnapshot
from toee_hermes.gateway.normalize import InboundChannelEvent
from toee_hermes.gateway.pipeline import InboundDecision

from hermes_runtime.gateway_app import create_app
from hermes_runtime.job_queue import AGENT_TURN_JOB_TYPE, PostgresJobQueue
from hermes_runtime.postgres_gateway_store import PostgresGatewayStore
from hermes_runtime.turn_runner import make_gateway_turn_runner
from hermes_runtime.turn_worker import (
    MAX_ERROR_BACKOFF_SECONDS,
    POLL_SECONDS,
    _error_backoff_seconds,
    poll_forever,
    run_once,
)

WEBHOOK_SECRET = "test-textline-shared-secret"
SIGNATURE_HEADER = "X-Textline-Signature"


# --------------------------------------------------------------------------
# fixtures + helpers
# --------------------------------------------------------------------------


@pytest.fixture
def wired(datastore):
    """``(driver, conn, store, queue)`` -- gateway store and queue on one schema."""
    driver, conn, _schema = datastore
    return driver, conn, PostgresGatewayStore(connection=conn), PostgresJobQueue(
        connection=conn
    )


def _row(conn, job_id: str, *columns: str):
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(columns)} FROM job WHERE id = %s",  # noqa: S608
            (job_id,),
        )
        return cur.fetchone()


def _serve_backoff(conn, job_id: str) -> None:
    """Fast-forward the retry backoff a reclaim/failure scheduled.

    The backoff itself is S01-tested (``test_expired_lease_is_reclaimed_and_
    becomes_claimable``); waiting 2 real seconds here would only slow the suite.
    """
    with conn.cursor() as cur:
        cur.execute("UPDATE job SET run_at = now() WHERE id = %s", (job_id,))
    conn.commit()


def _persisted_turn(store, conn, *, event_id: str, conversation_id: str, body: str):
    """Persist an accepted inbound; return ``(context, job_id)``.

    The enqueue is the store's, not the caller's (S02 fix wave 1): context and job
    row commit together, so there is no way to write a test that persists without
    enqueueing -- production cannot do that either, which is the whole point.
    """
    event = InboundChannelEvent(
        channel="textline_sms",
        provider="textline",
        event_id=event_id,
        conversation_id=conversation_id,
        from_phone="+15559876543",
        body=body,
        received_at="2026-01-01T00:00:00Z",
        raw_event_type="message.created",
        media_urls=None,
    )
    decision = InboundDecision(
        status=200,
        action="enqueue",
        stage="accept",
        event=event,
        snapshot=SessionIdentitySnapshot(
            outcome="unmatched_caller", resolved_at="2026-01-01T00:00:00Z"
        ),
    )
    context, _created = store.persist_accepted_inbound(decision)
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM job WHERE payload->>'event_id' = %s", (event_id,))
        rows = cur.fetchall()
    assert len(rows) == 1, f"expected exactly one turn job for {event_id}, got {rows}"
    return context, rows[0][0]


def _reply_runner(reply: str, *, sent: list, store=None, before=None):
    """A gateway turn runner whose model is a constant reply."""

    def run_turn(context: AgentTurnContext, inbound_body: str):
        if before is not None:
            before(context, inbound_body)
        return {"final_response": reply, "messages": []}

    return make_gateway_turn_runner(
        reply_sender=lambda conv, text: sent.append((conv, text)),
        run_turn=run_turn,
        on_reply_sent=(store.persist_agent_outbound if store is not None else None),
    )


def _sign(raw_body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def _inbound_payload(*, event_id: str, conversation_id: str, body: str) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "conversation_id": conversation_id,
            "from": "+15559876543",
            "body": body,
            "received_at": "2026-01-01T00:00:00Z",
            "type": "message.created",
        }
    ).encode("utf-8")


# --------------------------------------------------------------------------
# claim + run
# --------------------------------------------------------------------------


def test_run_once_claims_a_turn_job_runs_the_bound_turn_and_completes_it(wired):
    _driver, conn, store, queue = wired
    _context, job_id = _persisted_turn(
        store, conn, event_id="evt-w1", conversation_id="conv-w1", body="Got 225/65R17?"
    )
    sent: list = []

    job = run_once(
        queue=queue,
        store=store,
        turn_runner=_reply_runner("Yes, in stock.", sent=sent),
        worker="turn-worker-1",
    )

    assert job is not None and job.id == job_id
    assert sent == [("conv-w1", "Yes, in stock.")]
    assert _row(conn, job_id, "status", "locked_by") == ("succeeded", None)


def test_run_once_returns_none_when_no_turn_job_is_due(wired):
    _driver, _conn, store, queue = wired

    assert (
        run_once(
            queue=queue,
            store=store,
            turn_runner=_reply_runner("unused", sent=[]),
            worker="turn-worker-1",
        )
        is None
    )


def test_the_turn_worker_never_claims_a_background_job(wired):
    """FR-9 isolation: the turn worker's claim is an allowlist of one type, so a
    slow background job can neither be executed by it nor block a turn."""
    _driver, conn, store, queue = wired
    background_id = queue.enqueue({"anything": True}, job_type="retention_sweep")

    assert (
        run_once(
            queue=queue,
            store=store,
            turn_runner=_reply_runner("unused", sent=[]),
            worker="turn-worker-1",
        )
        is None
    )
    assert _row(conn, background_id, "status") == ("queued",)


def test_a_raising_turn_fails_the_job_with_its_error_and_leaves_it_retryable(wired):
    _driver, conn, store, queue = wired
    _context, job_id = _persisted_turn(
        store, conn, event_id="evt-w2", conversation_id="conv-w2", body="hello"
    )

    def _explode(context, inbound_body):
        raise RuntimeError("model timed out")

    job = run_once(
        queue=queue, store=store, turn_runner=_explode, worker="turn-worker-1"
    )

    assert job is not None and job.id == job_id
    status, attempts, last_error = _row(
        conn, job_id, "status", "attempts", "last_error"
    )
    assert (status, attempts) == ("failed", 1)
    assert "model timed out" in last_error


def test_a_turn_whose_context_is_missing_is_failed_not_silently_completed(wired):
    """A job whose context never persisted is a gateway bug, not a no-op: it has
    to end up visible (``last_error`` -> S05's dead-letter view), never
    ``succeeded``."""
    _driver, conn, store, queue = wired
    job_id = queue.enqueue(
        AgentJobPayload(event_id="evt-never-persisted", conversation_id="conv-x")
    )

    run_once(
        queue=queue,
        store=store,
        turn_runner=_reply_runner("unused", sent=[]),
        worker="turn-worker-1",
    )

    status, last_error = _row(conn, job_id, "status", "last_error")
    assert status == "failed"
    assert "context_not_found" in last_error


# --------------------------------------------------------------------------
# crash recovery (NFR-3 first half) -- the reason this slice exists
# --------------------------------------------------------------------------


def test_a_job_whose_worker_died_mid_turn_is_reclaimed_and_run_to_completion(wired):
    """US3: kill the worker mid-turn; the customer's message still gets answered.

    A ``SIGKILL``ed worker leaves its job ``running`` with a lease nobody will
    ever release. The next worker's poll sweeps expired leases before claiming,
    so the job returns to the queue and the *second* pass answers the message.

    RED-capable: without the sweep in ``run_once`` the row stays ``running``
    forever, the second ``run_once`` claims nothing, and the reply never happens.
    """
    _driver, conn, store, queue = wired
    context, job_id = _persisted_turn(
        store, conn, event_id="evt-crash", conversation_id="conv-crash", body="Any 17s?"
    )

    # The kill: worker-a claims the job and the process dies before completing it.
    killed = queue.claim(worker="turn-worker-a", types=(AGENT_TURN_JOB_TYPE,))
    assert killed is not None and killed.id == job_id
    assert _row(conn, job_id, "status") == ("running",)

    sent: list = []
    survivor = _reply_runner("Yes -- 225/65R17, $148 each.", sent=sent, store=store)

    # Pass 1: the sweep reclaims the dead lease; the job serves its retry backoff.
    assert (
        run_once(
            queue=queue,
            store=store,
            turn_runner=survivor,
            worker="turn-worker-b",
            lease_seconds=0,
        )
        is None
    )
    assert _row(conn, job_id, "status", "last_error") == ("failed", "lease expired")
    assert sent == []

    _serve_backoff(conn, job_id)

    # Pass 2: worker-b claims the reclaimed job and answers the customer.
    rerun = run_once(
        queue=queue,
        store=store,
        turn_runner=survivor,
        worker="turn-worker-b",
        lease_seconds=0,
    )

    assert rerun is not None and rerun.id == job_id
    assert sent == [("conv-crash", "Yes -- 225/65R17, $148 each.")]
    assert _row(conn, job_id, "status", "attempts") == ("succeeded", 2)

    # The reply is mirrored into message_turn -- the simulator/workbench evidence.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT body FROM message_turn WHERE customer_thread_id = %s "
            "AND author = 'hermes'",
            (context.customer_thread_id,),
        )
        assert [r[0] for r in cur.fetchall()] == ["Yes -- 225/65R17, $148 each."]


def test_a_crash_right_after_the_ack_still_leaves_the_turn_queued(wired):
    """US3, the narrowest crash there is: the gateway persisted the accepted
    inbound and the process died before *anything else* in the request ran.

    The provider already holds its 200, so nothing will be redelivered on its own
    schedule and nothing else knows the message exists. Unless the job row was
    written inside ``persist_accepted_inbound``'s own transaction, this is a
    silently lost customer message -- no job row, no dead-letter row, no trace.

    RED-capable: with the enqueue as a second, separate unit of work (the shape
    before this fix) no job exists here, ``run_once`` returns ``None``, and the
    customer is never answered.
    """
    _driver, conn, store, queue = wired
    context, _job_id = _persisted_turn(
        store,
        conn,
        event_id="evt-ack-crash",
        conversation_id="conv-ack-crash",
        body="Any 17s?",
    )
    sent: list = []

    # The restarted deployment's first poll.
    job = run_once(
        queue=queue,
        store=store,
        turn_runner=_reply_runner("Yes -- 225/65R17.", sent=sent, store=store),
        worker="turn-worker-restarted",
    )

    assert job is not None, "no job row: the acked message was lost"
    assert job.payload["event_id"] == context.event_id
    assert sent == [("conv-ack-crash", "Yes -- 225/65R17.")]
    assert _row(conn, job.id, "status") == ("succeeded",)


def test_a_stale_lease_holder_logs_lease_lost_and_never_reruns_the_turn(wired, caplog):
    """``LeaseLost`` is the fence working, not a retry signal (S01 decision 2):
    the loop logs it and moves on, because another worker owns the outcome now."""
    _driver, conn, store, queue = wired
    _context, job_id = _persisted_turn(
        store, conn, event_id="evt-stale", conversation_id="conv-stale", body="hi"
    )
    sent: list = []

    def _steal(context, inbound_body):
        # This worker is slow, not dead: while it runs, the sweep releases its
        # lease and worker-b claims the job.
        assert queue.reclaim_expired_leases(lease_seconds=0) == [job_id]
        _serve_backoff(conn, job_id)
        assert queue.claim(worker="turn-worker-b", types=(AGENT_TURN_JOB_TYPE,))

    slow = _reply_runner("late reply", sent=sent, before=_steal)

    with caplog.at_level(logging.WARNING, logger="hermes_runtime.turn_worker"):
        job = run_once(
            queue=queue,
            store=store,
            turn_runner=slow,
            worker="turn-worker-a",
            lease_seconds=3600,
        )

    assert job is not None and job.id == job_id
    assert len(sent) == 1  # ran exactly once; the loop did not retry it
    assert "lease" in caplog.text.lower()
    # worker-b still holds the row; the stale holder could not flip it.
    assert _row(conn, job_id, "status", "locked_by") == ("running", "turn-worker-b")


# --------------------------------------------------------------------------
# gateway -> queue -> worker, end to end
# --------------------------------------------------------------------------


def test_a_signed_webhook_enqueues_a_job_the_worker_turns_into_a_mirrored_reply(
    wired,
):
    """FR-10 acceptance: fast-ack writes a durable job row (not a thread), and a
    separate worker pass produces the reply in ``message_turn``."""
    driver, conn, store, queue = wired
    sent: list = []
    app = create_app(
        webhook_secret=WEBHOOK_SECRET,
        driver=driver,
        store=store,
        is_duplicate=store.is_duplicate,
    )
    raw = _inbound_payload(
        event_id="evt-e2e", conversation_id="conv-e2e", body="Do you have 225/65R17?"
    )

    response = TestClient(app).post(
        "/webhooks/textline", content=raw, headers={SIGNATURE_HEADER: _sign(raw)}
    )

    assert response.status_code == 200
    # Fast-ack left a durable row behind, and no reply has been sent yet.
    with conn.cursor() as cur:
        cur.execute("SELECT id, type, status FROM job")
        rows = cur.fetchall()
    assert len(rows) == 1 and rows[0][1:] == (AGENT_TURN_JOB_TYPE, "queued")
    assert sent == []

    job = run_once(
        queue=queue,
        store=store,
        turn_runner=_reply_runner("We do -- want a quote?", sent=sent, store=store),
        worker="turn-worker-1",
    )

    assert job is not None and job.id == rows[0][0]
    assert sent == [("conv-e2e", "We do -- want a quote?")]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM message_turn WHERE author = 'hermes' AND body = %s",
            ("We do -- want a quote?",),
        )
        assert cur.fetchone()[0] == 1


# --------------------------------------------------------------------------
# the loop around run_once: a database blip must not end the worker
# --------------------------------------------------------------------------


class _FlakyQueue:
    """Raises on the given (1-indexed) sweep numbers, behaves like an empty queue
    otherwise -- including failing again *after* a run of successes, so a test can
    catch a broken ``consecutive_failures`` reset. A counter that never resets
    would keep escalating the backoff across the second failure run instead of
    dropping back to the first-failure delay."""

    def __init__(self, fail_on_sweep: set[int]) -> None:
        self.fail_on_sweep = fail_on_sweep
        self.sweeps = 0

    def reclaim_expired_leases(self, *, lease_seconds: int) -> list:
        self.sweeps += 1
        if self.sweeps in self.fail_on_sweep:
            raise RuntimeError("connection to server was lost")
        return []

    def claim(self, *, worker: str, types=None):
        return None


def test_a_database_blip_backs_off_and_is_logged_instead_of_killing_the_worker(caplog):
    """``run_once``'s sweep/claim sit outside its try, so a transient Postgres
    error propagates. It must not end the process -- ``docs/ops/local-gateway.md``
    documents running this worker on the host, where an exit is permanent -- and it
    must stay loud: one logged exception per failure, never a silent swallow.

    Sweep 5 fails again after sweep 4 recovers, to prove ``consecutive_failures``
    actually resets on success: its backoff must land back at the first-failure
    delay (0.5s) rather than continuing the earlier escalation (which would show
    up as 4.0s if ``consecutive_failures = 0`` were deleted from ``poll_forever``).
    """
    queue = _FlakyQueue(fail_on_sweep={1, 2, 3, 5})
    slept: list[float] = []
    polls = {"n": 0}

    def _should_stop() -> bool:
        polls["n"] += 1
        return polls["n"] > 5  # 3 failures, 1 recovery, 1 failure again

    with caplog.at_level(logging.ERROR, logger="hermes_runtime.turn_worker"):
        poll_forever(
            queue=queue,
            store=None,
            turn_runner=None,
            worker="turn-worker-flaky",
            sleep=slept.append,
            should_stop=_should_stop,
        )

    assert queue.sweeps == 5
    # Every failure logged with its traceback -- a persistent outage stays visible.
    assert sum("Turn worker poll failed" in r.message for r in caplog.records) == 4
    # Escalates while failing (0.5, 1.0, 2.0), resets on the recovery (plain poll
    # interval), then escalates fresh from 0.5 again -- not 4.0, which is what a
    # deleted reset would produce.
    assert slept == [0.5, 1.0, 2.0, POLL_SECONDS, 0.5]


def test_the_error_backoff_is_bounded():
    """A long outage must not stretch the retry interval without limit."""
    assert _error_backoff_seconds(1) == 0.5
    assert _error_backoff_seconds(100) == MAX_ERROR_BACKOFF_SECONDS


# --------------------------------------------------------------------------
# fail-closed boot guard (fix wave 2): the worker is the destructive half
# --------------------------------------------------------------------------


def test_main_refuses_to_start_on_a_non_datastore_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``build_gateway_app`` already fails closed off a non-datastore backend
    (``test_gateway_composition``); the worker is the more destructive half of
    that same misconfiguration left unguarded -- with ``TOOL_BACKEND`` unset
    (the default) it would still open the real Postgres queue, claim real
    customer-turn jobs, look them up in its own empty per-process
    ``InMemoryGatewayStore``, and dead-letter every one of them after 3
    attempts, instead of merely failing to start. Pin that ``main()`` refuses
    before it builds anything (no DB connection needed for this to raise).
    """
    monkeypatch.delenv("TOOL_BACKEND", raising=False)

    from hermes_runtime.turn_worker import main

    with pytest.raises(ValueError, match="TOOL_BACKEND"):
        main()
