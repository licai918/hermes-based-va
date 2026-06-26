"""Datastore handlers for ``toee_eval_review`` (ADR-0074/0088/0040/0146).

Launch Eval runs are read for the Admin eval master-detail view (ADR-0088); the
governed mutations sign off a medium-severity failure and promote a passing
``policy_publish`` run. ADR-0146 cuts this over from the in-memory ``EvalStore``
(the behavioral source of truth) onto ``eval_run``: the full ADR-0074 report lives
in the ``report`` JSONB, and ``signed_off``/``promoted`` are independent, overlapping
governance flags overlaid from their own columns (a run can be both). Promotion is
**runId-keyed** with EvalStore-parity gating and, when the run carries a ``slot_key``,
publishes the matching kebab authoring slot on ``workbench_policy_slot`` (ADR-0145),
pushing the prior published text onto history so rollback has data (ADR-0146 closes
ADR-0145 divergence #2). Writes are fail-closed on an attributed actor and audited.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NoReturn, Optional

from psycopg.rows import dict_row

from toee_hermes.errors import ToolDriverError
from toee_hermes.operational_policy import authoring_slot_id_for

from ._common import insert_audit, new_id, read_string, serialize_row

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext


def _require_actor(context: "ToolExecutionContext") -> str:
    """The acting Supervisor Admin for a governed eval write, or a denial.

    Eval sign-off/promote are actor-attributed governance (ADR-0029/0088/0141):
    trusting an absent actor would write the mutation *and* a NULL-actor audit row
    while returning success. Fail closed so both eval write handlers are protected
    at once. (Mirrors ``accounts._require_actor`` / ``knowledge._require_actor``.)
    """
    actor = context.user_id
    if not actor:
        raise ToolDriverError(
            "policy_blocked", "A governed eval write requires an attributed actor."
        )
    return actor


def _eval_run_report(row: dict[str, Any]) -> dict[str, Any]:
    """The full ``EvalRunReport`` wire shape: the ADR-0074 report + the overlay.

    The PK ``id`` is the authoritative ``run_id`` (overlaid onto the stored report);
    ``signed_off``/``promoted`` are the governance overlay the on-disk report omits.
    """
    report = dict(row.get("report") or {})
    report["run_id"] = row["id"]
    report["signed_off"] = bool(row["signed_off"])
    report["promoted"] = bool(row["promoted"])
    return report


def _eval_run_summary(row: dict[str, Any]) -> dict[str, Any]:
    """The compact ``EvalRunSummary`` for the list pane (ADR-0088)."""
    report = row.get("report") or {}
    summary = report.get("summary") or {}
    failed_high = int(summary.get("failed_high") or 0)
    failed_medium = int(summary.get("failed_medium") or 0)
    return {
        "run_id": row["id"],
        "suite": report.get("suite"),
        "timestamp": report.get("timestamp"),
        "passed": failed_high == 0 and failed_medium == 0,
        "failed_high": failed_high,
        "failed_medium": failed_medium,
        "knowledge_version": report.get("knowledge_version"),
        "prompt_version": report.get("prompt_version"),
    }


def _run_row(conn, run_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, report, signed_off, promoted, slot_key"
            " FROM eval_run WHERE id = %s",
            (run_id,),
        )
        return serialize_row(cur.fetchone())


def _list_eval_runs(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    # listRuns parity: every run, most-recent-first. The store sorts by the report
    # timestamp string descending; an ISO-8601 text sort agrees. A read -> no actor,
    # no audit.
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, report, signed_off, promoted FROM eval_run"
            " ORDER BY (report ->> 'timestamp') DESC NULLS LAST, id DESC"
        )
        rows = cur.fetchall()
    return {"runs": [_eval_run_summary(serialize_row(row)) for row in rows]}


def _get_eval_run(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    run_id = read_string(params, "run_id", "runId")
    if run_id is None:
        raise ToolDriverError("unexpected_error", "run_id is required.")
    row = _run_row(conn, run_id)
    if row is None:
        raise ToolDriverError("not_found", "run not found")
    return {"run": _eval_run_report(row)}


def _sign_off_medium_failure(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    # signOffMedium parity: refuse when no medium sign-off is required, or when a
    # high-severity failure remains; else mark signed_off (idempotent). The gate is
    # in the atomic UPDATE so a concurrent change can't race the check; rowcount 0
    # is disambiguated into not_found (404) vs the two 409 messages.
    actor = _require_actor(context)
    run_id = read_string(params, "run_id", "runId")
    if run_id is None:
        raise ToolDriverError("unexpected_error", "run_id is required.")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE eval_run SET signed_off = TRUE
            WHERE id = %s
              AND COALESCE((report #>> '{summary,failed_high}')::int, 0) = 0
              AND COALESCE((report ->> 'signoff_required')::boolean, FALSE)
            RETURNING id, report, signed_off, promoted, slot_key
            """,
            (run_id,),
        )
        row = cur.fetchone()
    if row is None:
        _raise_sign_off_block(conn, run_id)
    insert_audit(
        conn,
        profile=context.profile,
        account_id=actor,
        action="sign_off_medium_failure",
        target_type="eval_run",
        target_id=run_id,
        details={},
    )
    return {"run": _eval_run_report(serialize_row(row))}


def _raise_sign_off_block(conn, run_id: str) -> NoReturn:
    """Disambiguate a sign-off rowcount 0 into the store's three reasons."""
    row = _run_row(conn, run_id)
    if row is None:
        raise ToolDriverError("not_found", "run not found")
    summary = (row.get("report") or {}).get("summary") or {}
    if int(summary.get("failed_high") or 0) > 0:
        raise ToolDriverError("conflict", "high-severity failures block sign-off")
    raise ToolDriverError("conflict", "no medium sign-off required")


def _promote_pending_policy(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    # promotePending parity: runId-keyed, gated by suite == policy_publish /
    # failed_high == 0 / sign-off, then mark promoted. ``NOT promoted`` makes the
    # mark idempotent (a re-promote returns ok without re-publishing). When the run
    # links an authoring slot, the same transaction publishes it (the ADR-0146
    # bridge). The driver commits on return / rolls back on raise, so the promote
    # flag, the history push, and the publish are atomic together.
    actor = _require_actor(context)
    run_id = read_string(params, "run_id", "runId")
    if run_id is None:
        raise ToolDriverError("unexpected_error", "run_id is required.")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE eval_run SET promoted = TRUE
            WHERE id = %s
              AND (report ->> 'suite') = 'policy_publish'
              AND COALESCE((report #>> '{summary,failed_high}')::int, 0) = 0
              AND (
                NOT COALESCE((report ->> 'signoff_required')::boolean, FALSE)
                OR signed_off
              )
              AND NOT promoted
            RETURNING id, report, signed_off, promoted, slot_key
            """,
            (run_id,),
        )
        row = cur.fetchone()
    if row is None:
        return _promote_already_or_block(conn, run_id)
    row = serialize_row(row)
    published_slot = _publish_authoring_slot(conn, row.get("slot_key"))
    insert_audit(
        conn,
        profile=context.profile,
        account_id=actor,
        action="promote_pending_policy",
        target_type="eval_run",
        target_id=run_id,
        details={"slot_key": row.get("slot_key"), "published_slot": published_slot},
    )
    return {"run": _eval_run_report(row)}


def _promote_already_or_block(conn, run_id: str) -> Any:
    """A promote rowcount 0 is an already-promoted no-op success or a 4xx block."""
    row = _run_row(conn, run_id)
    if row is None:
        raise ToolDriverError("not_found", "run not found")
    if row["promoted"]:
        # Idempotent: the run is already promoted (the publish already happened).
        return {"run": _eval_run_report(row)}
    report = row.get("report") or {}
    if report.get("suite") != "policy_publish":
        raise ToolDriverError("conflict", "run is not a promotable policy_publish run")
    summary = report.get("summary") or {}
    if int(summary.get("failed_high") or 0) > 0:
        raise ToolDriverError("conflict", "high-severity failures block promotion")
    raise ToolDriverError("conflict", "medium failures must be signed off first")


def _publish_authoring_slot(conn, slot_key: Optional[str]) -> Optional[str]:
    """Publish the kebab authoring slot a ``policy_publish`` run gates (ADR-0146).

    Maps the snake eval-gate ``slot_key`` to its kebab ``workbench_policy_slot`` id
    (ADR-0146 divergence #1 bridge — a direct PK update, never the wrong row),
    pushes the slot's current ``published_text`` onto ``workbench_policy_slot_history``
    (so rollback has data), then sets ``published_text = draft_text`` and ``status =
    'published'``. ``None`` slot_key -> nothing to publish (run marked only). An
    unknown key is refused rather than guessed. Returns the published kebab id (for
    audit) or ``None``.
    """
    if not slot_key:
        return None
    slot_id = authoring_slot_id_for(slot_key)
    if slot_id is None:
        raise ToolDriverError(
            "unexpected_error", f'no authoring slot for policy key "{slot_key}" (ADR-0146).'
        )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT draft_text, published_text FROM workbench_policy_slot"
            " WHERE slot_id = %s FOR UPDATE",
            (slot_id,),
        )
        slot = cur.fetchone()
        if slot is None:
            raise ToolDriverError(
                "conflict", "the authoring slot this run publishes no longer exists"
            )
        if slot["published_text"] is not None:
            cur.execute(
                "INSERT INTO workbench_policy_slot_history (id, slot_id, published_text)"
                " VALUES (%s, %s, %s)",
                (new_id("pshist"), slot_id, slot["published_text"]),
            )
        cur.execute(
            "UPDATE workbench_policy_slot"
            " SET published_text = draft_text, status = 'published', updated_at = now()"
            " WHERE slot_id = %s",
            (slot_id,),
        )
    return slot_id


def eval_review_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the eval-review datastore tool."""
    return {
        "toee_eval_review": {
            "list_eval_runs": _list_eval_runs,
            "get_eval_run": _get_eval_run,
            "sign_off_medium_failure": _sign_off_medium_failure,
            "promote_pending_policy": _promote_pending_policy,
        }
    }
