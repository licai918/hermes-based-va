"""Background worker: the durable consumer of every NON-turn job (0.0.4 S04).

FR-9 (background half) / FR-11, ADR-0155. The L6 learning fork, the Customer
Memory retention sweep and the knowledge corpus re-ingest used to run in three
different places -- inline on the copilot turn's thread, synchronously inside an
admin ``tools:dispatch`` call, and nowhere at all (a panel that printed a CLI
command). They are now three typed jobs on the one queue, and this process runs
them.

**Why a SECOND process rather than a wider turn worker (grilled decision 9).**
The isolation is the claim allowlist: this worker's ``types=`` never contains
``agent_turn`` and the turn worker's never contains any of these, so a corpus
re-ingest that takes minutes cannot claim, block, or queue ahead of a waiting
customer message. One shared loop with a wider allowlist would give exactly that
head-of-line blocking back.

**It also runs the schedule tick** (:meth:`PostgresJobQueue.tick_schedules`).
There is no cron anywhere in this repo and none is assumed (FR-8): the tick on
this loop IS the recurring mechanism, and the deterministic ``(type, window)``
dedupe key makes every extra tick a no-op. Before this slice retention was
manual-only; it is now button **and** cadence.

Run it::

    cd hermes-runtime && uv run python -m hermes_runtime.background_worker

or as the ``background-worker`` docker-compose service.

Shape is :mod:`hermes_runtime.turn_worker`'s, deliberately -- ``run_once`` is one
poll, ``poll_forever`` is the DB-outage-surviving shell, ``main`` fails closed on
``TOOL_BACKEND`` before building anything. Three differences, all named at their
constant: the ``types`` allowlist, a much longer :data:`POLL_SECONDS` (no
customer is waiting), and the ``tick_schedules`` call.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import time
from typing import Any, Callable, Mapping, Optional

from .job_queue import (
    DEFAULT_LEASE_SECONDS,
    INGEST_JOB_TYPE,
    INTEGRATION_PROBE_JOB_TYPE,
    L6_REVIEW_JOB_TYPE,
    RETENTION_JOB_TYPE,
    Job,
    LeaseLost,
    PostgresJobQueue,
    Schedule,
)

logger = logging.getLogger(__name__)

# FR-9 isolation IS this tuple. `agent_turn` is absent and must stay absent.
# Never pass None (that claims ANY type, customer turns included) and never ()
# (S01 fix #3: an empty allowlist claims nothing at all).
BACKGROUND_JOB_TYPES = (
    L6_REVIEW_JOB_TYPE,
    RETENTION_JOB_TYPE,
    INGEST_JOB_TYPE,
    INTEGRATION_PROBE_JOB_TYPE,
)

# ponytail: 5 s, against the turn worker's 250 ms. Nothing here has a latency
# budget -- NFR-2 is about a customer waiting on a reply, and no customer waits
# on a retention sweep. It also bounds the schedule tick's cost (one
# INSERT .. ON CONFLICT DO NOTHING per schedule per poll). The only human-facing
# consequence is that an admin "Run sweep now" / "Re-ingest" click takes up to
# 5 s to start; shorten it if that ever reads as broken.
POLL_SECONDS = 5.0

# ponytail: 4 pooled BUSINESS connections, same as the turn worker and for the
# same reason -- the loop is sequential, one job at a time. The deepest business
# nesting is the L6 fork's governed tool call inside a job whose claim/complete
# are their own committed units of work (2), so 4 is 2x headroom. Ingest is the
# job that "fans out" and it deliberately does NOT widen this: its heavy work
# talks to the SEPARATE toee_knowledge database (S-ISO pool) and opens its own
# direct connections, so it costs this pool nothing beyond the queue row.
# Raise it the day this worker runs jobs concurrently; it is a plain env var.
WORKER_POOL_MAX_SIZE = "4"

# The recurring work (FR-8's ticker). One entry today, on purpose.
#
# ponytail: 24 h for retention. The windows it enforces are 730 and 90 DAYS
# (ADR-0116 + the S28 addendum), so anything under a day buys nothing but write
# load, and anything over a day means a row can outlive its window by more than
# the sweep's own resolution. The pre-S04 documented cadence was the same:
# `0 3 * * *` in retention_sweep.py's old docstring. The window is
# floor(epoch/86400), i.e. midnight UTC -- a worker down for a whole UTC day
# misses that day rather than replaying a backlog (S01's recorded semantics),
# which is right for a cadence and wrong for nothing here.
#
# Ingest and l6_review are deliberately NOT scheduled: ingest needs an operator's
# fresh corpus artifact and TRUNCATEs the corpus, and l6_review is per-turn.
RETENTION_INTERVAL_SECONDS = 24 * 60 * 60

# ponytail: 15-minute integration-probe cadence (S16, FR-24). Unlike retention's
# 24 h, a health probe wants to catch an expired credential quickly -- 15 min bounds
# the /admin/integrations badge's staleness to a quarter-hour while writing ~96
# `job` rows/day (vs retention's 1). Cost of a SHORTER interval is linear `job`-row
# growth on a table whose retention is still blocked on replacing the dedupe
# guarantee (ADR-0153 fix #5), so shorten toward 5 min only if faster detection is
# worth that growth. The window is floor(epoch/900): every tick inside one 15-min
# window derives the SAME `schedule:integration_probe:<window>` dedupe key, so a
# duplicate tick -- or a worker restart mid-window -- is a no-op, exactly one probe
# per window. POLL_SECONDS (5 s) << the window, so the dedupe holds with wide margin.
INTEGRATION_PROBE_INTERVAL_SECONDS = 15 * 60

SCHEDULES: tuple[Schedule, ...] = (
    Schedule(job_type=RETENTION_JOB_TYPE, interval_seconds=RETENTION_INTERVAL_SECONDS),
    Schedule(
        job_type=INTEGRATION_PROBE_JOB_TYPE,
        interval_seconds=INTEGRATION_PROBE_INTERVAL_SECONDS,
    ),
)

# Where the corpus pull artifact (Stage A's output) lives for a queued re-ingest.
# ponytail: one env var, no payload field and no upload path -- the admin panel
# has no file picker and Stage A is an operator step by design (see
# knowledge/ingest.py's module docstring). Give the payload a `corpus_path` the
# day an operator needs to ingest two different artifacts.
INGEST_CORPUS_PATH_ENV = "INGEST_CORPUS_PATH"

JobBody = Callable[[Mapping[str, Any]], None]


class L6ReviewMisconfigured(RuntimeError):
    """An ``l6_review`` job reached a process that cannot durably run the fork.

    **Why this is a misconfiguration and not the default-OFF state.** The job's
    own existence proves the L6 flag was ON in the process that enqueued it:
    ``copilot_turn.run_turn``'s ``if agent_experience_enabled():`` is the only
    thing in the repo that enqueues this type, and nothing schedules it. So a
    flag that reads OFF *here* means the flag is split across the two processes
    (dispatch/copilot has it, this worker does not) -- exactly the gap S04 opened
    by moving the fork into a second process.

    Both halves of the check make the fork write **nothing** while the job would
    otherwise report ``succeeded``: with the flag off,
    ``_agent_experience_extra_drivers`` returns ``None`` and the governed
    ``propose_experience`` call lands in a throwaway per-process mock; with no
    ``OPENROUTER_API_KEY``, ``_run_review_pass`` returns ``[]`` without reaching a
    model at all. FR-11 promises the durable ``agent_experience`` row is identical
    after the move, so a silent no-op is a lost row, not a no-op.

    Shape borrowed from S03 fix wave 1's :class:`~hermes_runtime.outbound_send.OutboundSendBurned`:
    log at ERROR naming the variable and the consequence, then raise so the job
    fails and lands where a human sees it (``max_attempts=1`` -> straight to
    ``dead`` -> S05's dead-letter view), instead of reporting success.
    """


def _require_l6_writable() -> None:
    """Fail closed when this process cannot durably run an ``l6_review`` job."""
    from .openrouter import resolve_openrouter_config
    from .tool_backend import AGENT_EXPERIENCE_ENV, agent_experience_enabled

    if not agent_experience_enabled():
        logger.error(
            "An l6_review job was queued by a process with %s ON, but it is OFF on "
            "this worker: the review fork would run against the throwaway mock "
            "driver and persist NO agent_experience row. Failing the job; set %s "
            "on the background worker.",
            AGENT_EXPERIENCE_ENV,
            AGENT_EXPERIENCE_ENV,
        )
        raise L6ReviewMisconfigured(
            f"{AGENT_EXPERIENCE_ENV} is off on this worker but an l6_review job "
            "was enqueued; the fork would write nothing"
        )
    try:
        resolve_openrouter_config()
    except ValueError as exc:
        logger.error(
            "An l6_review job cannot run on this worker: %s. The fork would "
            "propose nothing and the job would report success having written "
            "no agent_experience row. Failing it instead.",
            exc,
        )
        raise L6ReviewMisconfigured(
            f"the l6_review fork has no review model on this worker: {exc}"
        ) from exc


def _run_ingest(payload: Mapping[str, Any]) -> None:
    """The ``ingest`` job body: Stage B over the operator's pull artifact."""
    from .knowledge.ingest import ingest

    corpus_path = payload.get("corpus_path") or os.environ.get(INGEST_CORPUS_PATH_ENV)
    if not corpus_path:
        raise RuntimeError(
            f"no corpus artifact to ingest: set {INGEST_CORPUS_PATH_ENV} on the "
            "background worker (see hermes_runtime.knowledge.ingest)"
        )
    result = ingest(corpus_path)
    logger.info(
        "Re-ingested %s chunks from %s docs (%s flagged)",
        result["chunk_count"],
        result["doc_count"],
        result["flagged_count"],
    )


def job_bodies() -> dict[str, JobBody]:
    """The job type -> body map. Imports are local: each body drags in a large
    subtree (the agent stack, the tool-dispatch stack, fastembed) and a worker
    should pay for them once at startup, not on import of this module."""
    from .copilot_turn import run_l6_review_job
    from .integration_probe import run_integration_probe_job
    from .retention_sweep import run_retention_sweep_job

    def l6_review(payload: Mapping[str, Any]) -> None:
        # The enqueue was gated on the L6 flag in ANOTHER process (S04 split them).
        # If this one is configured differently the fork writes nothing, so check
        # before running it rather than reporting success on a lost row.
        _require_l6_writable()
        # The proposals it returns were already persisted by the governed
        # propose_experience call inside the fork; the return value was only ever
        # an echo for the copilot result, and nothing reads it here.
        run_l6_review_job(payload)

    return {
        L6_REVIEW_JOB_TYPE: l6_review,
        RETENTION_JOB_TYPE: run_retention_sweep_job,
        INGEST_JOB_TYPE: _run_ingest,
        INTEGRATION_PROBE_JOB_TYPE: run_integration_probe_job,
    }


def _worker_name() -> str:
    """Identifies the lease holder in ``job.locked_by`` (operator-facing only)."""
    return f"background-worker@{socket.gethostname()}:{os.getpid()}"


def run_once(
    *,
    queue: PostgresJobQueue,
    bodies: Mapping[str, JobBody],
    worker: str,
    schedules: tuple[Schedule, ...] = SCHEDULES,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> Optional[Job]:
    """One poll: sweep dead leases, tick the schedules, claim one background job.

    Mirrors :func:`hermes_runtime.turn_worker.run_once` including its error
    contract: **no job failure escapes** (a poisonous job is failed and recorded,
    never allowed to kill the worker), but a queue error from the sweep/tick/claim
    does -- there is no job to fail, and :func:`poll_forever` catches and backs off.

    The sweep sits at the top of the poll rather than on a timer, so the crash
    drill exercises production code. It is safe against the lease fence: this
    loop is sequential, so nothing of ours is in flight while it runs, and it only
    ever touches *expired* leases. **No heartbeat / lease renewal exists**, on
    purpose -- rewriting ``locked_at`` mid-job rotates the fence token out from
    under its holder. See the report's note on long ingests.

    Both workers sweeping is fine and idempotent (S02's handoff).
    """
    for reclaimed in queue.reclaim_expired_leases(lease_seconds=lease_seconds):
        logger.warning(
            "Reclaimed job %s from an expired lease (a worker died mid-job)",
            reclaimed,
        )

    for created in queue.tick_schedules(schedules):
        logger.info("Schedule tick enqueued job %s", created)

    job = queue.claim(worker=worker, types=BACKGROUND_JOB_TYPES)
    if job is None:
        return None

    body = bodies.get(job.type)
    if body is None:
        # Only reachable if something enqueued a type this build cannot run --
        # a deploy skew or a typo. Fail it so it is visible in `last_error` and
        # ends up in S05's dead-letter view, never silently `succeeded`.
        logger.error("No handler for job %s of type %s", job.id, job.type)
        _fail(queue, job, f"no handler for job type {job.type}")
        return job

    try:
        body(job.payload)
    except Exception as exc:  # noqa: BLE001 - one bad job must not kill the worker
        # Identity keys only, never the payload body (it can carry draft text).
        logger.exception(
            "Background job %s (%s) failed on attempt %s/%s",
            job.id,
            job.type,
            job.attempts,
            job.max_attempts,
        )
        _fail(queue, job, f"{type(exc).__name__}: {exc}")
        return job

    try:
        queue.complete(job)
    except LeaseLost:
        # The fence working, not an error to retry: another worker owns the
        # outcome now (S01 decision 2).
        logger.warning(
            "Lease lost completing job %s; another worker owns it now", job.id
        )
    return job


def _fail(queue: PostgresJobQueue, job: Job, error: str) -> None:
    try:
        queue.fail(job, error)
    except LeaseLost:
        logger.warning("Lease lost failing job %s; another worker owns it now", job.id)


_stopping = False


def _request_stop(signum, frame) -> None:  # pragma: no cover - signal path
    """Finish the job in hand, then exit (SIGTERM from compose, SIGINT from Ctrl-C).

    Same reasoning as the turn worker's: the handler only sets a flag, so the
    in-flight ``run_once`` completes and releases its lease instead of stranding
    the job for the whole lease. SIGINT is handled too because a
    ``KeyboardInterrupt`` is a ``BaseException`` and would otherwise escape
    ``run_once`` mid-job.
    """
    global _stopping
    _stopping = True
    logger.info("Signal %s received; stopping after the current job", signum)


MAX_ERROR_BACKOFF_SECONDS = 60.0


def _error_backoff_seconds(consecutive_failures: int) -> float:
    """Exponential from the poll interval, capped. 1 -> 10s, 2 -> 20s, ... <= 60s."""
    return min(POLL_SECONDS * 2**consecutive_failures, MAX_ERROR_BACKOFF_SECONDS)


def poll_forever(
    *,
    queue: PostgresJobQueue,
    bodies: Mapping[str, JobBody],
    worker: str,
    sleep: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] = lambda: _stopping,
) -> None:
    """Run :func:`run_once` until asked to stop, surviving database outages.

    Every failure is logged in full -- a persistent outage stays loud -- and the
    backoff only decides how often, never whether.
    """
    consecutive_failures = 0
    while not should_stop():
        try:
            job = run_once(queue=queue, bodies=bodies, worker=worker)
        except Exception:  # noqa: BLE001 - a DB blip must not end the worker
            consecutive_failures += 1
            delay = _error_backoff_seconds(consecutive_failures)
            logger.exception(
                "Background worker poll failed (%s in a row); retrying in %.1fs",
                consecutive_failures,
                delay,
            )
            sleep(delay)
            continue
        consecutive_failures = 0
        if job is None:
            sleep(POLL_SECONDS)


def main() -> int:  # pragma: no cover - the process shell; run_once is the tested unit
    """Poll the queue until SIGTERM/Ctrl-C, which exits between jobs."""
    from toee_hermes.drivers.composio import require_composio_configuration

    from .gateway_composition import _require_datastore_backend

    # Fail closed BEFORE building anything (the S02 lesson). On a non-datastore
    # backend every job body here is either a no-op against a per-process mock or
    # writes to a store nobody else can see -- and the worker would still claim
    # and destroy real queued jobs while doing it.
    _require_datastore_backend()
    # Same posture for the Composio config (0.0.4 S12 fix wave 1): this worker
    # shares the image and the l6_review fork's tool surface, so it can build the
    # Composio driver too -- per job, not per process, until this check.
    require_composio_configuration()

    # Installed before the slow setup below, so SIGTERM/SIGINT take the graceful
    # path for the whole of boot, not just the loop.
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    # Set before anything builds the lazy process pool (datastore/pool.py reads
    # the env at construction); an explicit deployment value still wins.
    os.environ.setdefault("DATABASE_POOL_MAX_SIZE", WORKER_POOL_MAX_SIZE)

    bodies = job_bodies()
    queue = PostgresJobQueue()
    worker = _worker_name()
    logger.info(
        "Background worker %s polling for %s jobs every %ss (schedules: %s)",
        worker,
        ", ".join(BACKGROUND_JOB_TYPES),
        POLL_SECONDS,
        ", ".join(f"{s.job_type}/{s.interval_seconds}s" for s in SCHEDULES),
    )

    try:
        poll_forever(queue=queue, bodies=bodies, worker=worker)
    except KeyboardInterrupt:
        # Only reachable before the signal.signal calls above run at all
        # (interpreter/module-import startup).
        logger.info("Background worker %s interrupted before a job was claimed", worker)
    logger.info("Background worker %s stopped", worker)
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI shell
    raise SystemExit(main())
