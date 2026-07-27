"""The Customer Memory retention sweep's execution body (0.0.3 S28, FR-30,
ADR-0004/0116) plus its manual CLI shell.

Ages out ``customer_memory_slot`` rows per the class windows in
``hermes_runtime.datastore.handlers.retention``. Runs the SAME governed dispatch
path (``execute_tool``) the admin BFF's ``tools:dispatch`` trigger button used to
call directly, so the audit trail (``workbench_audit_log`` action
``retention_sweep``) -- and therefore the admin panel's "last run" -- is
byte-identical however the sweep was triggered.

**0.0.4 S04 (FR-11):** the sweep is now a queued ``retention`` job.
:func:`run_retention_sweep_job` is the job body the background worker runs; the
worker's schedule tick (``background_worker.SCHEDULES``) is what gives retention
a cadence for the first time, and the admin panel's button enqueues the same job
type (``toee_retention.enqueue_retention_sweep``). Only the caller moved: the
sweep, its windows, and its audit row are untouched.

The actor rides in the job payload, so an operator-triggered sweep still lands
its ``workbench_audit_log`` row attributed to the supervisor who clicked -- the
attribution the pre-S04 synchronous ``dispatchWrite`` gave it. A scheduled sweep
carries no actor, exactly like the unattended CLI run below.

CLI (unchanged, and it still sweeps SYNCHRONOUSLY -- it is the break-glass path
that must work with no worker running)::

    cd hermes-runtime && python -m hermes_runtime.retention_sweep
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from toee_hermes.execute import execute_tool
from toee_hermes.plugin.profiles import INTERNAL
from toee_hermes.tool_gate import ToolExecutionContext

from .datastore.driver import PostgresDriver


def run_sweep(
    *, profile: str = INTERNAL, actor_account_id: Optional[str] = None
) -> dict[str, Any]:
    """Execute one governed retention sweep; return its result payload.

    ``internal_copilot`` is the only profile ``toee_retention`` is allowlisted
    under (``hermes/toee_hermes/plugin/profiles.py``). ``actor_account_id`` is
    ``None`` for an unattended run (schedule or CLI) -- the same "no attributed
    actor" the cron-shaped entrypoint always had.

    Raises on a governed failure so a queued job FAILS (and eventually
    dead-letters) rather than reporting success on a sweep that never ran.
    """
    result = execute_tool(
        tool="toee_retention",
        action="trigger_retention_sweep",
        params={},
        context=ToolExecutionContext(profile=profile, user_id=actor_account_id),
        driver=PostgresDriver(),
    )
    if not result.ok:
        raise RuntimeError(f"retention sweep failed: {result.error_class}: {result.message}")
    return result.data


def run_retention_sweep_job(payload: Mapping[str, Any]) -> None:
    """The ``retention`` job body (S04). Payload carries the triggering actor.

    Known and accepted: unlike ``ingest``, this type keeps ``max_attempts=3``, so
    a sweep that outlives ``job_queue.DEFAULT_LEASE_SECONDS`` (300 s) is reclaimed
    back to ``failed`` and re-runs -- and with two background-worker replicas the
    reclaiming poll can be a different process than the one still sweeping. The
    DELETE is idempotent so the data outcome is unchanged; the visible cost is a
    SECOND ``retention_sweep`` audit row (and therefore a "last run" showing the
    later, mostly-empty sweep). Nobody has measured how close a real sweep gets to
    300 s; if it ever does, the fix is a per-type lease, not a heartbeat (which
    the S01 fence forbids).
    """
    run_sweep(
        profile=payload.get("profile") or INTERNAL,
        actor_account_id=payload.get("actor_account_id"),
    )


def main() -> int:
    try:
        data = run_sweep()
    except RuntimeError as exc:
        print(str(exc))
        return 1
    print(f"retention sweep OK: {data}")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI shell
    raise SystemExit(main())
