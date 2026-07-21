"""Turn worker: the durable consumer of inbound agent-turn jobs (0.0.4 S02).

FR-9/FR-10, ADR-0153. The gateway's fast-ack path used to hand the turn to a
daemon thread inside its own process (``LocalDispatchingJobQueue``, deleted with
this slice): a crash lost the customer's message with no record it ever existed.
Now the webhook writes one ``job`` row and *this* process claims it.

The job body is unchanged -- the same shared :func:`execute_agent_turn_job`
(reload by ``event_id``, verify the conversation binding, run the turn, ADR-0107)
the internal route runs. Only the execution substrate moved.

Run it::

    cd hermes-runtime && uv run python -m hermes_runtime.turn_worker

or as the ``turn-worker`` docker-compose service.

**Claim isolation (FR-9).** ``types=(AGENT_TURN_JOB_TYPE,)`` is an allowlist of
exactly one type, so this worker can never pick up a background job -- and S04's
background worker, with its own allowlist, can never pick up a customer turn.

**S04: copy this loop.** :func:`run_once` is the whole shape a sibling worker
needs -- sweep expired leases, claim one job of your own types, run it, then
``complete(job)`` / ``fail(job, ...)`` with the *object claim handed you* (that
object carries the lease credential the fence checks). ``LeaseLost`` is logged
and dropped, never retried: it means another worker legitimately owns the job now
and is responsible for its outcome. The only difference for S04 is the ``types``
allowlist, a slower poll interval, and a :meth:`PostgresJobQueue.tick_schedules`
call on the loop.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import time
from typing import Any, Callable, Optional

from toee_hermes.gateway.agent_turn import AgentJobPayload

from .agent_turn_job import AgentJobOutcome, execute_agent_turn_job
from .job_queue import (
    AGENT_TURN_JOB_TYPE,
    DEFAULT_LEASE_SECONDS,
    Job,
    LeaseLost,
    PostgresJobQueue,
)

logger = logging.getLogger(__name__)

# ADR-0153 §5: the poll interval IS the claim-latency knob (NFR-2), because the
# enqueue-to-claim gap is ~uniform(0, interval) -> p95 ~= 0.95 * interval.
#
# S01 named 1 s; measured, that is +981 ms p95 and misses NFR-2's < 500 ms budget,
# so this took ADR-0153 §5's named step (1) -- shorten the constant. Measured on
# the docker-compose Postgres: 1.0 s -> +981 ms p95, 0.5 s -> +495 ms (no margin),
# 0.25 s -> +263 ms. Step (2), LISTEN/NOTIFY with the poll kept as the correctness
# floor, is only worth it if the budget ever drops below ~100 ms.
#
# ponytail: the floor here is Postgres round-trips, not cleverness -- 4 claims +
# 4 lease sweeps per second per idle worker, both single-row indexed statements.
POLL_SECONDS = 0.25

# ponytail: this worker runs ONE turn at a time, so the process-wide default of
# 10 pooled connections (datastore/pool.py) is pure waste against the server's
# max_connections=100 -- 4 is the turn's own nesting depth (gateway store reload,
# the per-turn PostgresDriver tool overlay, the queue's own unit of work) plus
# headroom. Raise it the day the worker runs turns concurrently; it is a plain
# env var, so a deployment can already override it without a code change.
WORKER_POOL_MAX_SIZE = "4"


def _worker_name() -> str:
    """Identifies the lease holder in ``job.locked_by`` (operator-facing only)."""
    return f"turn-worker@{socket.gethostname()}:{os.getpid()}"


def run_once(
    *,
    queue: PostgresJobQueue,
    store: Any,
    turn_runner: Optional[Callable[[Any, str], None]],
    worker: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> Optional[Job]:
    """One poll: sweep dead leases, claim one turn job, run it. Never raises.

    Returns the claimed :class:`Job` (whatever its outcome) or ``None`` when
    nothing was due -- the caller sleeps only on ``None``, so a burst drains
    without paying a poll interval per job.

    The sweep is what makes a killed worker recoverable (NFR-3): a ``SIGKILL``ed
    process leaves its job ``running`` under a lease nobody will release, and
    only another worker's sweep can put it back. It cannot touch this worker's
    own in-flight job -- the loop is sequential, so nothing is in flight here
    while the sweep runs -- and it never rewrites ``locked_at`` on a *live*
    lease, which is what keeps the fence token stable for the holder.

    ``lease_seconds`` keeps the queue's 300 s default, so a killed worker's job
    becomes claimable ~5 minutes later plus the retry backoff -- that is the wait
    the PAC-2 kill drill sits through. Shortening it below the longest legitimate
    turn would start double-executing slow turns instead of recovering dead ones.
    """
    for reclaimed in queue.reclaim_expired_leases(lease_seconds=lease_seconds):
        logger.warning(
            "Reclaimed job %s from an expired lease (a worker died mid-job)",
            reclaimed,
        )

    job = queue.claim(worker=worker, types=(AGENT_TURN_JOB_TYPE,))
    if job is None:
        return None

    try:
        outcome = _run_turn(store=store, turn_runner=turn_runner, job=job)
    except Exception as exc:  # noqa: BLE001 - a turn must never kill the worker
        # Identity keys only, no PII body (ADR-0105).
        logger.exception(
            "Agent-turn job %s failed on attempt %s/%s (event_id=%s)",
            job.id,
            job.attempts,
            job.max_attempts,
            job.payload.get("event_id"),
        )
        _fail(queue, job, f"{type(exc).__name__}: {exc}")
        return job

    if outcome is not AgentJobOutcome.COMPLETED:
        # A missing context or a mismatched binding is a bug upstream, not a
        # no-op: fail it so it is visible in `last_error` and, once attempts are
        # spent, in S05's dead-letter view rather than silently `succeeded`.
        logger.warning(
            "Agent-turn job %s did not run a turn: %s", job.id, outcome.value
        )
        _fail(queue, job, outcome.value)
        return job

    try:
        queue.complete(job)
    except LeaseLost:
        # The fence working, not an error to retry: this job was reclaimed while
        # we were slow and another worker owns its outcome now (S01 decision 2).
        logger.warning(
            "Lease lost completing job %s; another worker owns it now", job.id
        )
    return job


def _run_turn(
    *, store: Any, turn_runner: Optional[Callable[[Any, str], None]], job: Job
) -> AgentJobOutcome:
    """The unchanged bound-turn job body, fed from the JSONB payload."""
    payload = AgentJobPayload(
        event_id=job.payload["event_id"],
        conversation_id=job.payload["conversation_id"],
    )
    return execute_agent_turn_job(
        store=store, turn_runner=turn_runner, payload=payload
    )


def _fail(queue: PostgresJobQueue, job: Job, error: str) -> None:
    try:
        queue.fail(job, error)
    except LeaseLost:
        logger.warning("Lease lost failing job %s; another worker owns it now", job.id)


_stopping = False


def _request_stop(signum, frame) -> None:  # pragma: no cover - signal path
    """Finish the job in hand, then exit (SIGTERM from `docker compose stop`).

    Without this a routine restart kills the worker mid-turn and that customer's
    turn sits stranded for the whole 300 s lease before another worker can
    reclaim it. The handler only sets a flag, so the in-flight ``run_once``
    completes and releases its lease normally.
    """
    global _stopping
    _stopping = True
    logger.info("Signal %s received; stopping after the current job", signum)


def main() -> int:  # pragma: no cover - the process shell; run_once is the tested unit
    """Poll the queue until SIGTERM/Ctrl-C, which exits between jobs."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    # Set before anything builds the lazy process pool (datastore/pool.py reads
    # the env at construction); an explicit deployment value still wins.
    os.environ.setdefault("DATABASE_POOL_MAX_SIZE", WORKER_POOL_MAX_SIZE)

    from .gateway_composition import resolve_turn_collaborators

    collaborators = resolve_turn_collaborators()
    queue = PostgresJobQueue()
    worker = _worker_name()
    logger.info(
        "Turn worker %s polling for %s jobs every %ss",
        worker,
        AGENT_TURN_JOB_TYPE,
        POLL_SECONDS,
    )

    signal.signal(signal.SIGTERM, _request_stop)

    try:
        while not _stopping:
            job = run_once(
                queue=queue,
                store=collaborators.store,
                turn_runner=collaborators.turn_runner,
                worker=worker,
            )
            if job is None:
                time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        logger.info("Turn worker %s stopping", worker)
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI shell
    raise SystemExit(main())
