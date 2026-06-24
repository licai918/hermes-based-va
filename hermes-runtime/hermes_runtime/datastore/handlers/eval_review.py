"""Datastore handlers for ``toee_eval_review`` (ADR-0074/0088/0040).

Launch Eval runs are read for the Admin eval master-detail view; the governed
mutations are signing off a medium-severity failure and promoting a slot's
pending policy to published (the publish eval-gate, ADR-0040). Promotion reuses
the same version lifecycle as ``toee_knowledge_ops`` via ``publish_pending_slot``.
Every mutation writes a Workbench Audit Log row in the same transaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg.rows import dict_row

from toee_hermes.errors import ToolDriverError

from ._common import insert_audit, read_string, serialize_row
from .knowledge import publish_pending_slot

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext


def _list_eval_runs(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, suite, status, failed_high, report, created_at
            FROM eval_run ORDER BY created_at DESC
            """
        )
        rows = cur.fetchall()
    return {"runs": [serialize_row(row) for row in rows]}


def _get_eval_run(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    run_id = read_string(params, "run_id", "runId")
    if run_id is None:
        raise ToolDriverError("unexpected_error", "run_id is required.")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, suite, status, failed_high, report, created_at
            FROM eval_run WHERE id = %s
            """,
            (run_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise ToolDriverError("unexpected_error", f"eval run {run_id} not found.")
    return {"run": serialize_row(row)}


def _sign_off_medium_failure(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    run_id = read_string(params, "run_id", "runId")
    if run_id is None:
        raise ToolDriverError("unexpected_error", "run_id is required.")
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM eval_run WHERE id = %s", (run_id,))
        if cur.fetchone() is None:
            raise ToolDriverError("unexpected_error", f"eval run {run_id} not found.")
        cur.execute(
            "UPDATE eval_run SET status = 'signed_off' WHERE id = %s", (run_id,)
        )
    insert_audit(
        conn,
        profile=context.profile,
        account_id=context.user_id,
        action="sign_off_medium_failure",
        target_type="eval_run",
        target_id=run_id,
        details={},
    )
    return {"run_id": run_id, "signed_off": True}


def _promote_pending_policy(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    slot = read_string(params, "slot")
    version = publish_pending_slot(conn, slot)
    insert_audit(
        conn,
        profile=context.profile,
        account_id=context.user_id,
        action="promote_pending_policy",
        target_type="policy_slot",
        target_id=slot,
        details={"version": version},
    )
    return {"slot": slot, "promoted": True, "status": "published"}


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
