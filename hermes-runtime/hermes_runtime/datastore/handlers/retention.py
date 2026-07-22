"""Datastore handler for ``toee_retention`` -- the Customer Memory retention
sweep (0.0.3 S28, FR-30, ADR-0004/0116).

Ages out ``customer_memory_slot`` rows whose ``last_interaction_at`` (never
``created_at`` -- the window refreshes on interaction, ADR-0116) is older than
its class window: 2 years for ``verified`` (non-negotiable), a shorter
90-day window for ``provisional`` (S28's recorded decision -- see
``toee_hermes.drivers.mock.retention``'s module docstring and the ADR-0116
addendum for the rationale). Both windows are the SAME constants the mock
twin and the pure unit tests use (``hermes/tests/test_retention_window.py`) --
one source of truth, no drift.

The sweep is one DELETE in the handler's existing transaction (``PostgresDriver
.execute`` commits/rolls back around the whole handler call, ADR-0140), so it
is atomic: either every aged row across both classes is removed and the audit
row lands, or nothing changes. Only ``customer_memory_slot`` is touched here --
NOT ``customer_memory_merge_audit`` (7-year retention, untouched) and NOT any
conversation-layer table.

Read-only counterpart ``get_retention_status`` derives "last run" + per-class
counts from the ``workbench_audit_log`` row the sweep itself writes (reusing
``insert_audit``, same governed-write audit trail every other handler in this
package uses) rather than a new sweep-state table -- no schema bloat for two
numbers a JSONB details column already carries.

0.0.4 S04 (FR-11) adds ``enqueue_retention_sweep``: the admin button and the
background worker's schedule tick both put a ``retention`` job on the durable
queue, and the worker runs ``trigger_retention_sweep`` below unchanged. The sweep
itself, its windows, and its audit row are untouched -- only the caller moved.
The *button* additionally writes its own ``retention_sweep_queued`` audit row, so
a click is recorded even if the worker never runs (S04 fix wave 1); nothing reads
that action, and ``get_retention_status`` still keys on ``retention_sweep`` alone.

All three actions are admin-only, never LLM-callable (see
``_AGENT_EXCLUDED_ACTIONS``) -- reached only from the admin BFF's deterministic
``tools:dispatch`` call, the background worker, or the CLI entrypoint
(``hermes_runtime.retention_sweep``), same precedent as
``get_memory_audit``/``list_agent_experience``/``get_aggregate_metrics``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from psycopg.rows import dict_row

from toee_hermes.drivers.mock.retention import (
    RETENTION_WINDOW_DAYS,
    retention_threshold,
)

from ._common import insert_audit

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext

_EMPTY_COUNTS = {"verified": 0, "provisional": 0}


def _trigger_retention_sweep(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    now = datetime.now(timezone.utc)
    verified_threshold = retention_threshold("verified", now)
    provisional_threshold = retention_threshold("provisional", now)

    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM customer_memory_slot
            WHERE (binding_kind = 'verified' AND last_interaction_at < %s)
               OR (binding_kind = 'provisional' AND last_interaction_at < %s)
            RETURNING binding_kind
            """,
            (verified_threshold, provisional_threshold),
        )
        deleted_kinds = [row[0] for row in cur.fetchall()]

    counts = dict(_EMPTY_COUNTS)
    for kind in deleted_kinds:
        if kind in counts:
            counts[kind] += 1
    total_deleted = len(deleted_kinds)
    run_at = now.isoformat()
    windows_days = dict(RETENTION_WINDOW_DAYS)

    insert_audit(
        conn,
        profile=context.profile,
        account_id=context.user_id,
        action="retention_sweep",
        target_type="customer_memory_slot",
        target_id=None,
        details={
            "counts": counts,
            "total_deleted": total_deleted,
            "windows_days": windows_days,
            "run_at": run_at,
        },
    )
    return {
        "counts": counts,
        "total_deleted": total_deleted,
        "windows_days": windows_days,
        "run_at": run_at,
    }


def _enqueue_retention_sweep(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    """Queue a ``retention`` job for the background worker (0.0.4 S04, FR-11).

    The admin panel's "Run sweep now" button used to call
    ``trigger_retention_sweep`` synchronously over ``tools:dispatch``. It now
    enqueues, so the DELETE runs on the one observable async substrate with the
    schedule ticks -- but the acting supervisor rides in the payload, so the
    ``workbench_audit_log`` row the sweep writes is attributed exactly as before.

    ``insert_job`` runs on the handler's own cursor, which ``PostgresDriver.execute``
    commits around (ADR-0140) -- every statement touching ``job`` still lives in
    ``job_queue.py``; this handler supplies a cursor, never SQL.

    **It audits the CLICK, matching its sibling ``enqueue_corpus_reingest``**
    (S04 fix wave 1, finding 4). Pre-S04 the sweep's own ``retention_sweep`` row
    was the whole record, which was complete because the DELETE happened inside
    the request. It no longer does: with the background worker down, a
    supervisor's click leaves only a ``job`` row and nothing in
    ``workbench_audit_log``. Two rows per completed sweep
    (``retention_sweep_queued`` then ``retention_sweep``) is the honest cost --
    ``get_retention_status`` reads the ``retention_sweep`` action only, so the
    panel's "last run" is unaffected. A SCHEDULED sweep writes no queued row at
    all: ``tick_schedules`` never calls this handler, so the cadence is as
    unattended as it was.
    """
    del params
    from hermes_runtime.job_queue import RETENTION_JOB_TYPE, insert_job

    with conn.cursor() as cur:
        job_id, _created = insert_job(
            cur,
            {"profile": context.profile, "actor_account_id": context.user_id},
            job_type=RETENTION_JOB_TYPE,
        )
    insert_audit(
        conn,
        profile=context.profile,
        account_id=context.user_id,
        action="retention_sweep_queued",
        target_type="customer_memory_slot",
        target_id=job_id,
        details={"job_id": job_id},
    )
    return {"job_id": job_id, "status": "queued"}


def _get_retention_status(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT created_at, details
            FROM workbench_audit_log
            WHERE action = 'retention_sweep'
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()

    if row is None:
        return {
            "last_run_at": None,
            "counts": dict(_EMPTY_COUNTS),
            "total_deleted": 0,
            "windows_days": dict(RETENTION_WINDOW_DAYS),
        }

    details = row["details"] or {}
    # Prefer the JSONB details' own run_at (the exact value the triggering
    # sweep returned) over the audit row's created_at column -- the two are
    # set by two different now() calls (Python vs Postgres DEFAULT) a few ms
    # apart, and a caller comparing this read against a just-triggered
    # sweep's response should see the identical timestamp, not a near-miss.
    last_run_at = details.get("run_at") or row["created_at"].isoformat()
    return {
        "last_run_at": last_run_at,
        "counts": details.get("counts", dict(_EMPTY_COUNTS)),
        "total_deleted": details.get("total_deleted", 0),
        "windows_days": details.get("windows_days", dict(RETENTION_WINDOW_DAYS)),
    }


def retention_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the Customer Memory retention sweep datastore tool."""
    return {
        "toee_retention": {
            "trigger_retention_sweep": _trigger_retention_sweep,
            "enqueue_retention_sweep": _enqueue_retention_sweep,
            "get_retention_status": _get_retention_status,
        }
    }
