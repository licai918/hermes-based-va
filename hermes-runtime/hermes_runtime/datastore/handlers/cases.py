"""Datastore handlers for ``toee_case``, ``toee_case_manage``, ``toee_workbench_read``.

Cases are the WorkbenchCase read model (ADR-0064/0065/0115). Each governed
mutation appends a Workbench Audit Log row in the *same* transaction (ADR-0029/
0085), so the write and its audit commit atomically. These real read/write shapes
supersede the admin-stub mock contracts (ADR-0068); Slice 35 maps them to the
BFF read model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from psycopg.rows import dict_row

from toee_hermes.errors import ToolDriverError

from ._common import insert_audit, new_id, read_string, serialize_row

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext


def _require_case_id(params: dict[str, Any]) -> str:
    case_id = read_string(params, "case_id", "caseId")
    if case_id is None:
        raise ToolDriverError("unexpected_error", "case_id is required.")
    return case_id


def _ensure_exists(conn, case_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM cases WHERE id = %s", (case_id,))
        if cur.fetchone() is None:
            raise ToolDriverError("unexpected_error", f"case {case_id} not found.")


def _status(conn, case_id: str) -> Optional[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM cases WHERE id = %s", (case_id,))
        row = cur.fetchone()
    return row[0] if row else None


def _case_row(conn, case_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM cases WHERE id = %s", (case_id,))
        row = cur.fetchone()
    out = serialize_row(row)
    if out is not None:
        out["case_id"] = out["id"]
    return out


def _create_case(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    contact_reason = read_string(params, "contact_reason", "contactReason")
    urgency = read_string(params, "urgency")
    summary = read_string(params, "summary")
    channel = read_string(params, "channel") or "sms"
    case_id = new_id("case")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO cases (id, channel, contact_reason, urgency, status, summary)
            VALUES (%s, %s, %s, %s, 'open', %s)
            """,
            (case_id, channel, contact_reason, urgency, summary),
        )
    record: dict[str, Any] = {"case_id": case_id, "status": "open", "channel": channel}
    if contact_reason is not None:
        record["contact_reason"] = contact_reason
    if urgency is not None:
        record["urgency"] = urgency
    if summary is not None:
        record["summary"] = summary
    return record


def _update_case(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    case_id = _require_case_id(params)
    _ensure_exists(conn, case_id)
    # update_case adjusts only urgency and contact_reason (ADR-0064).
    contact_reason = read_string(params, "contact_reason", "contactReason")
    urgency = read_string(params, "urgency")
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE cases SET
                contact_reason = COALESCE(%s, contact_reason),
                urgency = COALESCE(%s, urgency),
                last_activity_at = now()
            WHERE id = %s
            """,
            (contact_reason, urgency, case_id),
        )
    record: dict[str, Any] = {"case_id": case_id, "status": _status(conn, case_id)}
    if contact_reason is not None:
        record["contact_reason"] = contact_reason
    if urgency is not None:
        record["urgency"] = urgency
    return record


def _claim_case(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    case_id = _require_case_id(params)
    _ensure_exists(conn, case_id)
    # The claiming employee is the acting account; fall back to an explicit param.
    account_id = context.user_id or read_string(params, "assignee_id", "assigneeId")
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE cases SET
                assignee_account_id = COALESCE(%s, assignee_account_id),
                last_activity_at = now()
            WHERE id = %s
            """,
            (account_id, case_id),
        )
    insert_audit(
        conn,
        profile=context.profile,
        account_id=context.user_id,
        action="claim_case",
        target_type="case",
        target_id=case_id,
        details={"assignee_account_id": account_id},
    )
    return {"case_id": case_id, "claimed": True}


def _assign_case(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    case_id = _require_case_id(params)
    _ensure_exists(conn, case_id)
    assignee_id = read_string(params, "assignee_id", "assigneeId")
    if assignee_id is None:
        raise ToolDriverError("unexpected_error", "assignee_id is required.")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE cases SET assignee_account_id = %s, last_activity_at = now() WHERE id = %s",
            (assignee_id, case_id),
        )
    insert_audit(
        conn,
        profile=context.profile,
        account_id=context.user_id,
        action="assign_case",
        target_type="case",
        target_id=case_id,
        details={"assignee_account_id": assignee_id},
    )
    return {"case_id": case_id, "assignee_id": assignee_id, "assigned": True}


def _update_priority(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    case_id = _require_case_id(params)
    _ensure_exists(conn, case_id)
    # case_manage's "priority" maps to the case urgency column: ADR-0064 names the
    # adjustable field urgency, while ADR-0065 keeps the manage-action vocabulary.
    priority = read_string(params, "priority") or "normal"
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE cases SET urgency = %s, last_activity_at = now() WHERE id = %s",
            (priority, case_id),
        )
    insert_audit(
        conn,
        profile=context.profile,
        account_id=context.user_id,
        action="update_priority",
        target_type="case",
        target_id=case_id,
        details={"priority": priority},
    )
    return {"case_id": case_id, "priority": priority, "updated": True}


def _update_contact_reason(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    case_id = _require_case_id(params)
    _ensure_exists(conn, case_id)
    contact_reason = read_string(params, "contact_reason", "contactReason") or "general"
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE cases SET contact_reason = %s, last_activity_at = now() WHERE id = %s",
            (contact_reason, case_id),
        )
    insert_audit(
        conn,
        profile=context.profile,
        account_id=context.user_id,
        action="update_contact_reason",
        target_type="case",
        target_id=case_id,
        details={"contact_reason": contact_reason},
    )
    return {"case_id": case_id, "contact_reason": contact_reason, "updated": True}


def _resolve_case(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    case_id = _require_case_id(params)
    _ensure_exists(conn, case_id)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE cases SET
                status = 'resolved',
                resolved_at = now(),
                resolved_by_account_id = %s,
                last_activity_at = now()
            WHERE id = %s
            """,
            (context.user_id, case_id),
        )
    insert_audit(
        conn,
        profile=context.profile,
        account_id=context.user_id,
        action="resolve_case",
        target_type="case",
        target_id=case_id,
        details={},
    )
    return {"case_id": case_id, "status": "resolved"}


def _get_case(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    case_id = _require_case_id(params)
    # A missing case is a legitimate empty read, not a tool failure: return null
    # rather than fabricate or raise (ADR-0020).
    return {"case": _case_row(conn, case_id)}


def _list_cases(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    status = read_string(params, "status")
    with conn.cursor(row_factory=dict_row) as cur:
        if status is not None:
            cur.execute(
                "SELECT * FROM cases WHERE status = %s ORDER BY last_activity_at DESC",
                (status,),
            )
        else:
            cur.execute("SELECT * FROM cases ORDER BY last_activity_at DESC")
        rows = cur.fetchall()
    cases = []
    for row in rows:
        serialized = serialize_row(row)
        serialized["case_id"] = serialized["id"]
        cases.append(serialized)
    return {"cases": cases}


def _get_audit_log(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    case_id = _require_case_id(params)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT * FROM workbench_audit_log
            WHERE target_type = 'case' AND target_id = %s
            ORDER BY created_at ASC
            """,
            (case_id,),
        )
        rows = cur.fetchall()
    return {"case_id": case_id, "entries": [serialize_row(r) for r in rows]}


def case_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the case-centric datastore tools."""
    return {
        "toee_case": {
            "create_case": _create_case,
            "update_case": _update_case,
        },
        "toee_case_manage": {
            "claim_case": _claim_case,
            "assign_case": _assign_case,
            "update_priority": _update_priority,
            "update_contact_reason": _update_contact_reason,
            "resolve_case": _resolve_case,
        },
        "toee_workbench_read": {
            "get_case": _get_case,
            "list_cases": _list_cases,
            "get_audit_log": _get_audit_log,
        },
    }
