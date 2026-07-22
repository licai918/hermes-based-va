"""0.0.4 S03 (FR-12 / NFR-3): a retried or replayed turn never sends twice.

S02's recovery is what created this hazard. A worker killed mid-turn leaves its
job ``running``; the next worker's sweep reclaims it and runs the turn again --
and until this slice that second run POSTed the customer a second copy of a reply
they already had, and wrote a second ``message_turn`` mirror row for the
Workbench (and for S17's email channel, where the mirror *is* the reply).

The drill is ``test_a_reclaimed_turn_reruns_without_re_sending_the_reply``: worker
A claims, delivers, and dies before ``complete``; worker B reclaims and re-runs.
Exactly one send, exactly one mirror row, and a counted skip on the
``outbound_send`` row so an operator can see the suppression rather than guess at
it. Delete the ``deliver_once`` wrap from ``make_gateway_turn_runner`` and it goes
red on two sends.

Live-Postgres, skip-if-no-DB via the shared ``datastore`` fixture (a migrated
throwaway schema), so these never touch dev data (ADR-0142 local-first).
"""

from __future__ import annotations

import pytest

from toee_hermes.gateway.agent_turn import AgentTurnContext
from toee_hermes.gateway.ingress import SessionIdentitySnapshot
from toee_hermes.gateway.normalize import InboundChannelEvent, to_inbound_email_event
from toee_hermes.gateway.pipeline import InboundDecision

from hermes_runtime.job_queue import PostgresJobQueue
from hermes_runtime.outbound_send import (
    InMemoryOutboundSendLog,
    OutboundSendBurned,
    OutboundSendLog,
    deliver_once,
    outbound_idempotency_key,
)
from hermes_runtime.postgres_gateway_store import PostgresGatewayStore
from hermes_runtime.turn_runner import make_gateway_turn_runner
from hermes_runtime.turn_worker import run_once


# --------------------------------------------------------------------------
# fixtures + helpers
# --------------------------------------------------------------------------


@pytest.fixture
def wired(datastore):
    """``(conn, store, queue, log)`` -- every S03 collaborator on one schema."""
    _driver, conn, _schema = datastore
    return (
        conn,
        PostgresGatewayStore(connection=conn),
        PostgresJobQueue(connection=conn),
        OutboundSendLog(connection=conn),
    )


def _sms_decision(*, event_id: str, conversation_id: str, body: str) -> InboundDecision:
    event = InboundChannelEvent(
        channel="simpletexting_sms",
        provider="simpletexting",
        event_id=event_id,
        conversation_id=conversation_id,
        from_phone="+15559876543",
        body=body,
        received_at="2026-01-01T00:00:00Z",
        raw_event_type="message.created",
        media_urls=None,
    )
    return InboundDecision(
        status=200,
        action="enqueue",
        stage="accept",
        event=event,
        snapshot=SessionIdentitySnapshot(
            outcome="unmatched_caller", resolved_at="2026-01-01T00:00:00Z"
        ),
    )


def _email_decision(*, event_id: str, conversation_id: str) -> InboundDecision:
    event = to_inbound_email_event(
        event_id=event_id,
        conversation_id=conversation_id,
        from_address="accounts@acme-fleet.example",
        subject="Order 10444",
        body="Where is my order?",
        received_at="2026-01-01T00:00:00Z",
    )
    return InboundDecision(
        status=200,
        action="enqueue",
        stage="accept",
        event=event,
        snapshot=SessionIdentitySnapshot(
            outcome="unmatched_caller", resolved_at="2026-01-01T00:00:00Z"
        ),
    )


def _persisted_turn(store, conn, decision):
    """Persist + enqueue atomically (S02 fix wave 1); return ``(context, job_id)``."""
    context, _created = store.persist_accepted_inbound(decision)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM job WHERE payload->>'event_id' = %s",
            (decision.event.event_id,),
        )
        rows = cur.fetchall()
    assert len(rows) == 1, f"expected one turn job, got {rows}"
    return context, rows[0][0]


def _runner(reply: str, *, sent: list, store=None, log=None):
    """A gateway turn runner whose model is a constant reply."""

    def run_turn(context, inbound_body):
        return {"final_response": reply, "messages": []}

    def reply_sender(conversation_id: str, text: str) -> None:
        sent.append((conversation_id, text))

    return make_gateway_turn_runner(
        reply_sender=reply_sender,
        run_turn=run_turn,
        on_reply_sent=(store.persist_agent_outbound if store is not None else None),
        outbound_log=log,
    )


def _outbound_row(conn, event_id: str, *columns: str):
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(columns)} FROM outbound_send WHERE event_id = %s",  # noqa: S608
            (event_id,),
        )
        return cur.fetchone()


def _mirror_bodies(conn, session_id: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT body FROM message_turn
             WHERE sms_session_id = %s AND direction = 'outbound'
             ORDER BY id
            """,
            (session_id,),
        )
        return [r[0] for r in cur.fetchall()]


def _seed_outbound_row(
    conn, *, event_id: str, conversation_id: str, status: str, error=None
) -> None:
    """Put a row on the table by hand -- the state a killed process leaves behind.

    No handler ran, so nothing in the code path produced it: that is the point.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO outbound_send
                (idempotency_key, job_id, event_id, conversation_id, channel,
                 status, last_error)
            VALUES (%s, NULL, %s, %s, 'simpletexting_sms', %s, %s)
            """,
            (f"killed:{event_id}:reply", event_id, conversation_id, status, error),
        )
    conn.commit()


def _job_row(conn, job_id: str):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, attempts, last_error FROM job WHERE id = %s", (job_id,)
        )
        return cur.fetchone()


def _serve_backoff(conn, job_id: str) -> None:
    """Fast-forward the retry backoff a reclaim scheduled (S02's helper, verbatim)."""
    with conn.cursor() as cur:
        cur.execute("UPDATE job SET run_at = now() WHERE id = %s", (job_id,))
    conn.commit()


def _expire_lease(conn, job_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE job SET locked_at = now() - interval '1 hour' WHERE id = %s",
            (job_id,),
        )
    conn.commit()


# --------------------------------------------------------------------------
# the key derivation (unit, no DB)
# --------------------------------------------------------------------------


def test_the_key_is_derived_from_framework_identity_and_nothing_else() -> None:
    key = outbound_idempotency_key(job_id="job_abc", event_id="evt-1")

    # Both inputs are visible in the key, so an auditor reads the lineage off the
    # row without a join (FR-13 "original idempotency lineage kept").
    assert "job_abc" in key and "evt-1" in key
    # Deterministic: two derivations of the same turn agree.
    assert key == outbound_idempotency_key(job_id="job_abc", event_id="evt-1")
    # ADR-0148: the signature admits no model output and no tool parameter, so
    # there is nothing a reply body could change.
    with pytest.raises(TypeError):
        outbound_idempotency_key(  # type: ignore[call-arg]
            job_id="job_abc", event_id="evt-1", body="pick a new key please"
        )


def test_a_turn_delivered_with_no_job_still_gets_a_stable_key() -> None:
    # The ADR-0106 parity route has no job row. The key must still be stable
    # across two executions of the same turn, or the route is an unguarded path.
    first = outbound_idempotency_key(job_id=None, event_id="evt-1")
    assert first == outbound_idempotency_key(job_id=None, event_id="evt-1")
    assert "evt-1" in first


def test_deliver_once_runs_the_action_once_and_records_the_skip() -> None:
    log = InMemoryOutboundSendLog()
    calls: list[int] = []

    for _ in range(3):
        deliver_once(
            log=log,
            job_id="job_1",
            event_id="evt-1",
            conversation_id="conv-1",
            deliver=lambda: calls.append(1),
        )

    assert calls == [1]
    assert log.rows["evt-1"]["status"] == "sent"
    assert log.rows["evt-1"]["skip_count"] == 2


# --------------------------------------------------------------------------
# the crash drill (live Postgres)
# --------------------------------------------------------------------------


def test_a_reclaimed_turn_reruns_without_re_sending_the_reply(wired) -> None:
    """NFR-3 / PAC-2: worker A dies after delivering; worker B must not re-send."""
    conn, store, queue, log = wired
    context, job_id = _persisted_turn(
        store,
        conn,
        _sms_decision(
            event_id="evt-crash", conversation_id="conv-crash", body="Got 225/65R17?"
        ),
    )
    sent: list = []
    runner = _runner("Yes, in stock.", sent=sent, store=store, log=log)

    # Worker A: claim, run the turn (the reply IS delivered), then die -- never
    # completes, so the row stays `running` under a lease nobody will release.
    job_a = queue.claim(worker="worker-a", types=("agent_turn",))
    assert job_a is not None and job_a.id == job_id
    runner(context, "Got 225/65R17?", job_a.id)
    assert sent == [("conv-crash", "Yes, in stock.")]

    # Worker B: the sweep reclaims the dead lease, the backoff is served, and the
    # SAME turn runs again -- exactly the re-run S02 made possible.
    _expire_lease(conn, job_id)
    assert run_once(queue=queue, store=store, turn_runner=runner, worker="worker-b") is None
    _serve_backoff(conn, job_id)
    job_b = run_once(queue=queue, store=store, turn_runner=runner, worker="worker-b")

    assert job_b is not None and job_b.id == job_id
    assert sent == [("conv-crash", "Yes, in stock.")], "the customer was texted twice"
    assert _mirror_bodies(conn, context.sms_session_id) == ["Yes, in stock."]

    key, status, skips = _outbound_row(
        conn, "evt-crash", "idempotency_key", "status", "skip_count"
    )
    assert status == "sent"
    assert skips == 1, "the suppressed re-send must be recorded, not invisible"
    assert key == outbound_idempotency_key(job_id=job_id, event_id="evt-crash")


def test_an_intent_row_from_a_killed_process_blocks_the_re_send_quietly(wired) -> None:
    """The state FR-12 actually names: SIGKILL/power loss, no handler ever ran.

    An ``intent`` row is what a process that got *no* chance to run any ``except``
    leaves behind, and it is indistinguishable from the outside from "the POST
    landed and the commit did not". This test writes that row directly -- no
    exception, no handler -- so it is the real crash state and not the
    rejected-send path.

    **Pinned meaning: ``intent`` on a re-run is "assume sent".** The brief's
    at-most-once direction ("a crash between POST and commit must be treated as
    already-sent"): the re-run delivers nothing, raises nothing, and the job
    completes. The cost is a reply lost in that narrow window; the alternative is
    texting a customer twice.
    """
    conn, store, queue, log = wired
    context, job_id = _persisted_turn(
        store,
        conn,
        _sms_decision(
            event_id="evt-window", conversation_id="conv-window", body="Any 18in?"
        ),
    )
    _seed_outbound_row(
        conn, event_id="evt-window", conversation_id="conv-window", status="intent"
    )

    sent: list = []
    survivor = _runner("We do.", sent=sent, store=store, log=log)
    survivor(context, "Any 18in?", job_id)  # must not raise: the turn is done

    assert sent == [], "an intent row must block the re-send"
    assert _mirror_bodies(conn, context.sms_session_id) == []
    assert _outbound_row(conn, "evt-window", "status", "skip_count") == ("intent", 1)


def test_a_rejected_send_is_recorded_and_still_never_re_posts(wired) -> None:
    conn, store, queue, log = wired
    context, job_id = _persisted_turn(
        store,
        conn,
        _sms_decision(event_id="evt-reject", conversation_id="conv-reject", body="Hi"),
    )

    def _reject(conversation_id: str, text: str) -> None:
        raise RuntimeError("SimpleTexting rejected the reply (HTTP 500)")

    runner = make_gateway_turn_runner(
        reply_sender=_reject,
        run_turn=lambda ctx, body: {"final_response": "Hello!", "messages": []},
        on_reply_sent=store.persist_agent_outbound,
        outbound_log=log,
    )
    with pytest.raises(RuntimeError):
        runner(context, "Hi", job_id)

    status, error = _outbound_row(conn, "evt-reject", "status", "last_error")
    assert status == "failed"
    assert "SimpleTexting rejected" in error

    # The job's own retry comes back here. It must not re-post -- and it must not
    # pretend the turn succeeded either: this reply never reached the customer, so
    # it raises and the job goes on to dead-letter (fix wave 1, finding 1).
    attempts: list = []
    retry = _runner("Hello!", sent=attempts, store=store, log=log)
    with pytest.raises(OutboundSendBurned):
        retry(context, "Hi", job_id)
    assert attempts == []


def test_a_burned_reply_dead_letters_instead_of_reporting_success(wired) -> None:
    """A reply nobody will ever send must reach a human, not a green job.

    The previous attempt failed to reach the provider, so the key is spent. The
    job must burn its remaining attempts and land in the ``dead`` rows S05's
    dead-letter view reads -- not complete as ``succeeded`` having sent nothing.
    """
    conn, store, queue, log = wired
    context, job_id = _persisted_turn(
        store,
        conn,
        _sms_decision(event_id="evt-burn", conversation_id="conv-burn", body="Hi"),
    )
    _seed_outbound_row(
        conn,
        event_id="evt-burn",
        conversation_id="conv-burn",
        status="failed",
        error="RuntimeError: SimpleTexting rejected the reply (HTTP 500)",
    )
    sent: list = []
    runner = _runner("Hello!", sent=sent, store=store, log=log)

    for _ in range(3):
        assert run_once(
            queue=queue, store=store, turn_runner=runner, worker="w"
        ) is not None
        _serve_backoff(conn, job_id)

    status, attempts, last_error = _job_row(conn, job_id)
    assert sent == [], "a burned key must never re-post"
    assert status == "dead", "the operator must see this in the dead-letter view"
    assert attempts == 3
    assert "OutboundSendBurned" in last_error


# --------------------------------------------------------------------------
# the composite delivery: POST + mirror are two actions in one wrap
# --------------------------------------------------------------------------


def _mirror_failing_runner(reply: str, *, sent: list, log, boom: str):
    def _mirror(context, text: str) -> None:
        raise RuntimeError(boom)

    return make_gateway_turn_runner(
        reply_sender=lambda cid, text: sent.append((cid, text)),
        run_turn=lambda ctx, body: {"final_response": reply, "messages": []},
        on_reply_sent=_mirror,
        outbound_log=log,
    )


def test_a_mirror_failure_after_the_send_is_not_recorded_as_a_failed_send(
    wired,
) -> None:
    """The customer HAS the SMS; only the Workbench mirror is missing (finding 4).

    Recording that as ``failed`` would tell the operator the opposite of what
    happened. The record says ``sent`` -- true, and it is what stops a re-text --
    and ``last_error`` carries the mirror failure so the job still dead-letters
    and a human goes and fixes the thread row.
    """
    conn, store, queue, log = wired
    context, job_id = _persisted_turn(
        store,
        conn,
        _sms_decision(event_id="evt-mirror", conversation_id="conv-mirror", body="Hi"),
    )
    sent: list = []
    runner = _mirror_failing_runner(
        "Hello!", sent=sent, log=log, boom="message_turn insert failed"
    )

    with pytest.raises(RuntimeError):
        runner(context, "Hi", job_id)

    status, error = _outbound_row(conn, "evt-mirror", "status", "last_error")
    assert sent == [("conv-mirror", "Hello!")]
    assert status == "sent", "the customer has the reply; do not call the send failed"
    assert "message_turn insert failed" in error

    # And the retry still cannot re-text -- but it is loud, not silently green.
    with pytest.raises(OutboundSendBurned):
        _runner("Hello!", sent=sent, store=store, log=log)(context, "Hi", job_id)
    assert sent == [("conv-mirror", "Hello!")]


def test_on_email_a_mirror_failure_is_a_failed_send(wired) -> None:
    """On email the mirror IS the delivery, so its failure is a send failure."""
    conn, store, queue, log = wired
    context, job_id = _persisted_turn(
        store,
        conn,
        _email_decision(event_id="evt-mirror-mail", conversation_id="conv-mirror-mail"),
    )
    sent: list = []
    runner = _mirror_failing_runner(
        "Shipped Tuesday.", sent=sent, log=log, boom="message_turn insert failed"
    )

    with pytest.raises(RuntimeError):
        runner(context, "Where is my order?", job_id)

    # Nothing reached the customer on this channel, so `sent` would be a lie.
    assert _outbound_row(conn, "evt-mirror-mail", "status")[0] == "failed"


# --------------------------------------------------------------------------
# the other two outbound surfaces
# --------------------------------------------------------------------------


def test_a_replayed_email_turn_writes_no_second_mirror_row(wired) -> None:
    """S17: on the email channel the ``message_turn`` mirror IS the reply."""
    conn, store, queue, log = wired
    context, job_id = _persisted_turn(
        store,
        conn,
        _email_decision(event_id="evt-email-s03", conversation_id="conv-email-s03"),
    )
    assert context.channel == "simulated_email"
    sent: list = []
    runner = _runner("Shipped Tuesday.", sent=sent, store=store, log=log)

    runner(context, "Where is my order?", job_id)
    runner(context, "Where is my order?", job_id)

    assert _mirror_bodies(conn, context.sms_session_id) == ["Shipped Tuesday."]
    # And the SMS provider is never called on an email turn (ADR-0153, RK-4): the
    # sender strips its argument to digits, so an email conversation_id that
    # happened to look like a phone number would become a real, billable SMS.
    # The mirror above is the whole delivery -- which is exactly why it still sits
    # inside the same deliver_once wrap.
    assert sent == []
    assert _outbound_row(conn, "evt-email-s03", "channel", "skip_count") == (
        "simulated_email",
        1,
    )


def test_the_simulated_reply_sender_goes_through_the_same_wrap(wired) -> None:
    """0.0.3 S01's ``REPLY_SENDER=simulated`` no-op is a delivery, not an exemption."""
    from hermes_runtime.gateway_composition import _simulated_reply_sender

    conn, store, queue, log = wired
    context, job_id = _persisted_turn(
        store,
        conn,
        _sms_decision(event_id="evt-sim", conversation_id="conv-sim", body="Hours?"),
    )
    runner = make_gateway_turn_runner(
        reply_sender=_simulated_reply_sender,
        run_turn=lambda ctx, body: {"final_response": "9-5 Mon-Fri.", "messages": []},
        on_reply_sent=store.persist_agent_outbound,
        outbound_log=log,
    )

    runner(context, "Hours?", job_id)
    runner(context, "Hours?", job_id)

    # The simulator reads replies out of message_turn, so a duplicate mirror row
    # is a duplicate reply in the simulator thread -- the E2E gate's evidence.
    assert _mirror_bodies(conn, context.sms_session_id) == ["9-5 Mon-Fri."]
    assert _outbound_row(conn, "evt-sim", "status", "skip_count") == ("sent", 1)


def test_a_replay_under_a_new_job_id_still_cannot_re_send(wired) -> None:
    """S05's Replay is safe even if it mints a new job row rather than resetting."""
    conn, store, queue, log = wired
    context, job_id = _persisted_turn(
        store,
        conn,
        _sms_decision(event_id="evt-replay", conversation_id="conv-replay", body="Hi"),
    )
    sent: list = []
    runner = _runner("Hello!", sent=sent, store=store, log=log)

    runner(context, "Hi", job_id)
    runner(context, "Hi", "job_a_brand_new_row")

    assert sent == [("conv-replay", "Hello!")]
    # The FIRST send's key survives -- that is the "original idempotency lineage"
    # FR-13 asks Replay to keep.
    assert _outbound_row(conn, "evt-replay", "idempotency_key", "job_id") == (
        outbound_idempotency_key(job_id=job_id, event_id="evt-replay"),
        job_id,
    )


def test_two_different_turns_on_one_conversation_both_send(wired) -> None:
    """The guard is per inbound turn, not per conversation -- a follow-up must reply."""
    conn, store, queue, log = wired
    sent: list = []
    for event_id, reply in (("evt-t1", "Yes."), ("evt-t2", "Tuesday.")):
        context, job_id = _persisted_turn(
            store,
            conn,
            _sms_decision(
                event_id=event_id, conversation_id="conv-multi", body="question"
            ),
        )
        _runner(reply, sent=sent, store=store, log=log)(context, "question", job_id)

    assert sent == [("conv-multi", "Yes."), ("conv-multi", "Tuesday.")]


def test_the_wrap_records_the_conversation_binding_for_the_auditor(wired) -> None:
    conn, store, queue, log = wired
    context, job_id = _persisted_turn(
        store,
        conn,
        _sms_decision(event_id="evt-audit", conversation_id="conv-audit", body="Hi"),
    )
    _runner("Hello!", sent=[], store=store, log=log)(context, "Hi", job_id)

    assert _outbound_row(
        conn, "evt-audit", "job_id", "conversation_id", "channel", "status"
    ) == (job_id, "conv-audit", "simpletexting_sms", "sent")


def test_an_unbound_context_is_not_needed_to_read_the_record(wired) -> None:
    """The record is queryable by job id -- S05's dead-letter view joins on it."""
    conn, store, queue, log = wired
    context, job_id = _persisted_turn(
        store,
        conn,
        _sms_decision(event_id="evt-byjob", conversation_id="conv-byjob", body="Hi"),
    )
    _runner("Hello!", sent=[], store=store, log=log)(context, "Hi", job_id)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_id, status FROM outbound_send WHERE job_id = %s", (job_id,)
        )
        assert cur.fetchall() == [("evt-byjob", "sent")]


def test_a_context_without_a_session_still_records_the_send(wired) -> None:
    """The mirror short-circuits on a missing session; the record must not."""
    conn, store, queue, log = wired
    context = AgentTurnContext(
        event_id="evt-nosession",
        conversation_id="conv-nosession",
        sms_session_id="",
        customer_thread_id="",
        from_phone="+15559876543",
        session_identity_snapshot=None,
        inbound_body_ref="ref",
    )
    sent: list = []
    runner = _runner("Hello!", sent=sent, store=store, log=log)

    runner(context, "Hi", "job_nosession")
    runner(context, "Hi", "job_nosession")

    assert sent == [("conv-nosession", "Hello!")]
    assert _outbound_row(conn, "evt-nosession", "status", "skip_count") == ("sent", 1)
