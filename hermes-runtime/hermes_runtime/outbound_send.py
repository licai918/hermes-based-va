"""Outbound send record + the one idempotency wrap (0.0.4 S03, FR-12 / NFR-3).

S02 made a crashed turn recoverable -- the lease sweep re-claims it and the turn
runs again -- and that recovery is precisely what makes a second copy of an
already-delivered reply possible. Every customer-facing action a turn takes now
goes through :func:`deliver_once`: it writes an ``intent`` row **before** the
delivery and flips it to ``sent`` after, so a retried or replayed turn finds the
row and skips the whole delivery.

**One wrap, not one guard per sender.** ``deliver_once`` takes a single
``deliver`` callable, and :func:`hermes_runtime.turn_runner.make_gateway_turn_runner`
puts the *entire* delivery step inside it -- the Textline POST (or the
``REPLY_SENDER=simulated`` no-op that stands in for it, 0.0.3 S01) *and* the
``message_turn`` reply mirror (0.0.3 S17, which is the email channel's whole
outbound surface). There is deliberately no per-sender guard: three guards is
three chances for a fourth outbound path to be added beside them.

**The key is derived, never supplied** (ADR-0148). :func:`outbound_idempotency_key`
takes the job id and the inbound ``event_id`` -- both framework context. Nothing
the model emitted, and no tool parameter, reaches it: a model that could choose
the key could choose to send twice.

**Ordering, and what each crash point means.**

1. ``begin`` inserts the intent row and **commits**;
2. no row inserted (someone else owns the send) -> record the skip, return False;
3. ``deliver()`` -- the POST and the mirror;
4. ``finish`` marks the row ``sent``.

A crash *before* the POST and a crash *after the POST but before the commit* both
leave the row at ``intent``, and nothing can tell them apart from the outside.
Both are therefore treated as already-sent on the re-run: **at-most-once toward
the customer** is the deliberate trade FR-12 asks for. The cost is named in the
``ponytail:`` ceiling on :func:`deliver_once`.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional

import psycopg

from .datastore.config import database_url
from .datastore.pool import get_database_pool

logger = logging.getLogger(__name__)

# The one outbound action a turn takes today: the single customer-facing reply.
# It is part of the key so the key says what it identifies.
_REPLY_SLOT = "reply"

# Stands in for the job id on the ADR-0106 parity route, which delivers a turn
# with no job row behind it. The key is only *lineage*; the guarantee is the
# UNIQUE (event_id) index, which does not care (migration 0012).
_NO_JOB = "no-job"


def outbound_idempotency_key(*, job_id: Optional[str], event_id: str) -> str:
    """The deterministic key for a turn's one outbound reply (FR-12).

    Inputs are framework context only -- the queue's job id and the provider's
    inbound event id. **Never** model output or a tool parameter (ADR-0148):
    identity-bearing values come from the framework, so no reply text, no
    conversation body, and no tool argument can move the key and buy a second
    send.

    Stable across a replay because both inputs are: ``event_id`` is the
    customer's inbound message, and FR-13's Replay resets the *existing* job row
    rather than inserting a new one (see S05 note in the slice report). Should a
    job id ever differ between two executions of the same turn, the key differs
    but the guarantee does not -- ``UNIQUE (event_id)`` still admits exactly one
    row, and the first send's key stays as the recorded lineage.
    """
    return f"{job_id or _NO_JOB}:{event_id}:{_REPLY_SLOT}"


class OutboundSendLog:
    """The ``outbound_send`` table. Same two connection modes as the job queue.

    Every method is its own unit of work and **commits before returning** -- that
    is the whole mechanism: the intent must be durable before the delivery it
    guards, or a crash in between is invisible.
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
    def _unit_of_work(self) -> Iterator[psycopg.Cursor]:
        if self._connection is not None:
            conn = self._connection
            try:
                with conn.cursor() as cur:
                    yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            return
        with get_database_pool(self._dsn).connection() as conn:
            try:
                with conn.cursor() as cur:
                    yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def begin(
        self,
        *,
        key: str,
        job_id: Optional[str],
        event_id: str,
        conversation_id: str,
        channel: str = "",
    ) -> bool:
        """Write-ahead the intent. True when *this* caller owns the send.

        False means a row for this turn already exists -- sent, or left at
        ``intent`` by a process that died mid-delivery. Either way the caller
        must not deliver. The conflict target is ``event_id``, not the key, for
        the reason spelled out in migration 0012.
        """
        with self._unit_of_work() as cur:
            cur.execute(
                """
                INSERT INTO outbound_send
                    (idempotency_key, job_id, event_id, conversation_id, channel)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO NOTHING
                RETURNING idempotency_key
                """,
                (key, job_id, event_id, conversation_id, channel),
            )
            return cur.fetchone() is not None

    def record_skip(self, *, event_id: str) -> None:
        """Count the suppressed re-send on the existing row (the audit trail).

        A skip that leaves no trace is indistinguishable from a turn that never
        tried to reply, which is exactly the question an operator asks after a
        crash (PAC-2). ``skip_count``/``last_skipped_at`` on the row are the
        answer, and they sit next to the key so the lineage is one row.
        """
        with self._unit_of_work() as cur:
            cur.execute(
                """
                UPDATE outbound_send
                   SET skip_count = skip_count + 1,
                       last_skipped_at = now(),
                       updated_at = now()
                 WHERE event_id = %s
                """,
                (event_id,),
            )

    def finish(self, key: str, *, status: str, error: Optional[str] = None) -> None:
        """Close the record: ``sent`` after a clean delivery, ``failed`` after a raise."""
        with self._unit_of_work() as cur:
            cur.execute(
                """
                UPDATE outbound_send
                   SET status = %s, last_error = %s, updated_at = now()
                 WHERE idempotency_key = %s
                """,
                (status, error, key),
            )


class InMemoryOutboundSendLog:
    """Process-local ``OutboundSendLog`` for the DB-free callers.

    ``create_app()`` and the tests that build it boot with no database at all
    (see :func:`hermes_runtime.gateway_app.create_app`), and this is what keeps
    them on the *same* wrap rather than on an unguarded fallback branch -- an
    ``if log is None: deliver()`` escape hatch is how a second delivery path gets
    reintroduced. One process, one dict, so "durable before the send" is free.
    """

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def begin(
        self,
        *,
        key: str,
        job_id: Optional[str],
        event_id: str,
        conversation_id: str,
        channel: str = "",
    ) -> bool:
        if event_id in self.rows:
            return False
        self.rows[event_id] = {
            "idempotency_key": key,
            "job_id": job_id,
            "event_id": event_id,
            "conversation_id": conversation_id,
            "channel": channel,
            "status": "intent",
            "skip_count": 0,
            "last_error": None,
        }
        return True

    def record_skip(self, *, event_id: str) -> None:
        row = self.rows.get(event_id)
        if row is not None:
            row["skip_count"] += 1

    def finish(self, key: str, *, status: str, error: Optional[str] = None) -> None:
        for row in self.rows.values():
            if row["idempotency_key"] == key:
                row["status"] = status
                row["last_error"] = error
                return


def deliver_once(
    *,
    log: Any,
    job_id: Optional[str],
    event_id: str,
    conversation_id: str,
    channel: str = "",
    deliver: Callable[[], None],
) -> bool:
    """Run ``deliver`` at most once for this turn. True if it ran, False if skipped.

    ``deliver`` is the *whole* outbound step -- POST and mirror together -- so
    the record covers everything the customer or the Workbench would see twice.

    ponytail: an existing row is absolute, including the ``failed`` one a
    rejected POST leaves behind, so a Textline outage burns that turn's reply
    rather than risking a duplicate. That is the at-most-once trade FR-12 asks
    for and it is the safe direction, but it does mean the job's remaining
    retries can no longer deliver. Ceiling named rather than fixed: the upgrade
    path is to record the provider's response on the row and let *only* a
    definitive non-2xx (request completed, message rejected -- never a timeout,
    which may have delivered) reopen the key for one more attempt.
    """
    key = outbound_idempotency_key(job_id=job_id, event_id=event_id)
    if not log.begin(
        key=key,
        job_id=job_id,
        event_id=event_id,
        conversation_id=conversation_id,
        channel=channel,
    ):
        log.record_skip(event_id=event_id)
        # Identity keys only, never the reply body (ADR-0105).
        logger.warning(
            "Outbound send already recorded for event %s (job %s); skipping the "
            "delivery -- the customer has this reply already",
            event_id,
            job_id,
        )
        return False

    try:
        deliver()
    except Exception as exc:  # noqa: BLE001 - recorded, re-raised, never re-sent
        try:
            log.finish(key, status="failed", error=f"{type(exc).__name__}: {exc}")
        except Exception:  # noqa: BLE001 - bookkeeping must not mask the real failure
            # The row stays `intent`, which still blocks the re-send; only the
            # reason is lost. Losing the reason is much cheaper than losing the
            # exception that explains the outage.
            logger.exception("Could not record the failed outbound send %s", key)
        raise
    log.finish(key, status="sent")
    return True
