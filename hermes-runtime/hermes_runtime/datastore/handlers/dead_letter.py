"""Datastore handlers for ``toee_job_queue`` -- the dead-letter operator view and
governed Replay (0.0.4 S05, FR-13).

S01 gave the queue a terminal ``dead`` status, S02/S04 put every async trigger on
it, S03 made outbound sends idempotent. This is the human end of that: a
supervisor sees what is stuck and can put ONE job back on the queue, attributed
and audited.

**Two lists, because a dead job is not the only way work goes wrong.**

``jobs`` is FR-13's core -- ``status = 'dead'`` rows with type, payload summary,
attempts, ``last_error`` and timestamps, each joined to the ``outbound_send``
record it left behind (S03's ``idx_outbound_send_job``, which exists for exactly
this question: did this job already text the customer?).

``outbound`` is the states S03/S04 leave that NO dead-letter row captures, split
into buckets an operator can act on differently:

===================  ==========================================================
``send_failed``      The provider refused. The customer got nothing and nothing
                     will retry -- a reply, or (``slot = 'opt-out'``) the
                     ADR-0016 confirmation a customer who opted out never
                     received. A human decides whether to text them by hand.
``mirror_missing``   ``sent`` with a ``last_error``: the customer HAS the SMS
                     but the ``message_turn`` mirror never landed, so the
                     workbench thread is permanently incomplete. Do NOT re-send.
``stale_intent``     An ``intent`` row older than :data:`_STALE_INTENT_SECONDS`.
                     A process died between recording intent and the POST; the
                     re-run skipped quietly and **the job succeeded**, so this
                     is invisible everywhere else in the system. Nothing sweeps
                     these (deliberately -- S05 surfaces, it does not sweep).
===================  ==========================================================

Both actions are admin-only (``_AGENT_EXCLUDED_ACTIONS``) -- reached only from
the admin BFF's deterministic ``tools:dispatch`` call, never a live agent's tool
loop. The toolset is allowlisted on ``supervisor_admin`` (ADR-0038): this is an
operations surface, so it is supervisor+admin in the workbench (ADR-0093 gives
``/admin/*`` exactly that), deliberately unlike a credential surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg.rows import dict_row
from toee_hermes.errors import ToolDriverError

from ._common import insert_audit, read_string, serialize_row

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext

# ponytail: no pagination and no filters -- the whole point of a dead-letter view
# is that it is normally empty, and 100 stuck jobs is already an incident rather
# than a page-2 problem. Add a cursor the day an operator hits the cap.
_LIST_LIMIT = 100

# How old an `intent` row must be before it is a stuck send rather than one in
# flight. Sized at 3x DEFAULT_LEASE_SECONDS (300s): a turn that is still legally
# running holds a lease, and one lease plus its retry backoff is the longest a
# healthy `intent` row can honestly live.
# ponytail: a constant, not a per-channel policy. Make it configurable the day a
# channel's delivery is genuinely slower than an SMS POST.
_STALE_INTENT_SECONDS = 900

# A payload value's cap in the triage list. `l6_review` carries the entire review
# prompt (draft text included); the view is a list, not a transcript.
_SUMMARY_CHARS = 160

_JOB_COLUMNS = (
    "j.id, j.type, j.payload, j.attempts, j.max_attempts, j.last_error,"
    " j.run_at, j.created_at, j.updated_at"
)


def _summarize(payload: Any) -> dict[str, Any]:
    """Keys with short values -- long strings truncated, containers collapsed."""
    if not isinstance(payload, dict):
        return {}
    summary: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, str) and len(value) > _SUMMARY_CHARS:
            summary[key] = value[:_SUMMARY_CHARS] + "…"
        elif isinstance(value, (dict, list)):
            summary[key] = f"<{type(value).__name__} of {len(value)}>"
        else:
            summary[key] = value
    return summary


def _list_dead_letters(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    # A read -> no actor required, no audit (parity with get_retention_status).
    del params, context
    from hermes_runtime.job_queue import replay_blocked_reason

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT {_JOB_COLUMNS},
                   o.status AS outbound_status,
                   o.skip_count AS outbound_skip_count,
                   o.last_error AS outbound_last_error
            FROM job j
            LEFT JOIN outbound_send o ON o.job_id = j.id
            WHERE j.status = 'dead'
            ORDER BY j.updated_at DESC
            LIMIT {_LIST_LIMIT}
            """  # noqa: S608 - both interpolations are module constants
        )
        job_rows = [serialize_row(row) for row in cur.fetchall()]

        cur.execute(
            """
            SELECT idempotency_key, job_id, event_id, conversation_id, channel,
                   status, skip_count, last_error, created_at, updated_at,
                   regexp_replace(idempotency_key, '^.*:', '') AS slot
            FROM outbound_send
            WHERE status = 'failed'
               OR (status = 'sent' AND last_error IS NOT NULL)
               OR (status = 'intent'
                   AND updated_at < now() - make_interval(secs => %s))
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            (_STALE_INTENT_SECONDS, _LIST_LIMIT),
        )
        outbound_rows = [serialize_row(row) for row in cur.fetchall()]

    jobs = []
    for row in job_rows:
        blocked = replay_blocked_reason(row["type"])
        outbound_status = row["outbound_status"]
        jobs.append(
            {
                "job_id": row["id"],
                "type": row["type"],
                "payload_summary": _summarize(row["payload"]),
                "attempts": row["attempts"],
                "max_attempts": row["max_attempts"],
                "last_error": row["last_error"],
                "run_at": row["run_at"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "replayable": blocked is None,
                "replay_blocked_reason": blocked,
                "outbound": (
                    None
                    if outbound_status is None
                    else {
                        "status": outbound_status,
                        "skip_count": row["outbound_skip_count"],
                        "last_error": row["outbound_last_error"],
                    }
                ),
            }
        )

    outbound = [{**row, "bucket": _bucket(row)} for row in outbound_rows]
    return {"jobs": jobs, "outbound": outbound}


def _bucket(row: dict[str, Any]) -> str:
    if row["status"] == "failed":
        return "send_failed"
    if row["status"] == "sent":
        return "mirror_missing"
    return "stale_intent"


def _require_actor(context: "ToolExecutionContext") -> str:
    """The acting supervisor for a governed replay, or a denial (ADR-0148).

    The actor rides ``ToolExecutionContext.user_id``, asserted by the BFF from
    the signed-in session under the shared bearer -- NEVER a request param.
    Fail closed: an unattributed replay would put work back on the queue and
    write a NULL-actor audit row while reporting success. (Mirrors
    ``knowledge._require_actor``.)
    """
    actor = context.user_id
    if not actor:
        raise ToolDriverError(
            "policy_blocked", "A governed job replay requires an attributed actor."
        )
    return actor


def _replay_job(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    """Return one dead job to the queue, attributed and audited (FR-13).

    Order matters: actor first (fail closed), then the type check, then the
    reset -- so a blocked or unattributed replay leaves both the ``job`` row and
    the audit log untouched. The reset and the audit row share the handler's
    transaction (``PostgresDriver.execute`` commits around the whole call,
    ADR-0140), so a replay is never recorded without happening.

    No bulk replay in v1 (PRD default): one ``job_id``, one row. That is also
    what keeps ``ingest`` safe -- see ``REPLAY_BLOCKED_JOB_TYPES``.
    """
    from hermes_runtime.job_queue import replay_blocked_reason, replay_dead_job

    job_id = read_string(params, "job_id", "jobId")
    if not job_id:
        raise ToolDriverError("unexpected_error", "job_id is required.")
    actor = _require_actor(context)

    with conn.cursor() as cur:
        cur.execute("SELECT type, attempts FROM job WHERE id = %s AND status = 'dead'", (job_id,))
        row = cur.fetchone()
        if row is None:
            raise ToolDriverError("not_found", f"no dead job {job_id}.")
        job_type, attempts_before = row

        blocked = replay_blocked_reason(job_type)
        if blocked is not None:
            raise ToolDriverError("policy_blocked", blocked)

        replayed_type = replay_dead_job(cur, job_id)
        if replayed_type is None:  # raced another replay between the two statements
            raise ToolDriverError("not_found", f"no dead job {job_id}.")

    insert_audit(
        conn,
        profile=context.profile,
        account_id=actor,
        action="job_replayed",
        target_type="job",
        target_id=job_id,
        details={"type": job_type, "attempts_before": attempts_before},
    )
    return {"job_id": job_id, "type": job_type, "status": "queued"}


def dead_letter_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the dead-letter view + governed replay."""
    return {
        "toee_job_queue": {
            "list_dead_letters": _list_dead_letters,
            "replay_job": _replay_job,
        }
    }


__all__ = ["dead_letter_handlers"]
