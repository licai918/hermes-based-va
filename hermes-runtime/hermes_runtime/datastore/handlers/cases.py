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

import os

from toee_hermes.drivers.mock.textline import TextlineMockData, _send_message
from toee_hermes.errors import ToolDriverError

from toee_hermes.identity.summary import (
    display_name_from_match_result,
    format_identity_summary,
)

from ._common import insert_audit, new_id, read_string, serialize_row

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext


def _require_case_id(params: dict[str, Any]) -> str:
    case_id = read_string(params, "case_id", "caseId")
    if case_id is None:
        raise ToolDriverError("unexpected_error", "case_id is required.")
    return case_id


def _require_actor(context: "ToolExecutionContext") -> str:
    """The acting workbench account for a governed write, or a governed denial.

    A ``toee_case_manage`` write is the point of actor-attributed audit (ADR-0029/
    0141): the actor rides ``ToolExecutionContext.user_id``, which the BFF asserts
    under the shared bearer. Trusting an absent actor would, for claim/resolve,
    write a NULL mutation *and* a NULL-actor audit row while still returning
    success — a silent wrong-success. Fail closed at this one shared boundary so
    every write handler is protected at once: no attributed actor, no write.
    """
    actor = context.user_id
    if not actor:
        raise ToolDriverError(
            "policy_blocked", "A governed case write requires an attributed actor."
        )
    return actor


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


# WorkbenchCase.urgent is a boolean; the cases table stores a free urgency label
# (ADR-0064). These labels render as urgent in the ADR-0079 queue.
_URGENT_URGENCIES = {"urgent", "high"}


def _thread_display_name(conn, channel: str, channel_identity: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT match_result FROM session_identity_snapshot
            WHERE channel = %s AND channel_identity = %s
              AND match_result->>'outcome' = 'verified_customer'
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            (channel, channel_identity),
        )
        row = cur.fetchone()
    return display_name_from_match_result(row[0]) if row else None


def _thread_identity_summary(conn, thread_id: Optional[str]) -> str:
    """ADR-0082 identity summary: verified Shopify customer name + phone, else phone."""
    if not thread_id:
        return ""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT channel, channel_identity, shopify_customer_id"
            " FROM customer_thread WHERE id = %s",
            (thread_id,),
        )
        row = cur.fetchone()
    if row is None:
        return ""
    channel_identity = row.get("channel_identity") or ""
    shopify_customer_id = row.get("shopify_customer_id")
    display_name = _thread_display_name(conn, row.get("channel") or "sms", channel_identity)
    return format_identity_summary(
        channel_identity=channel_identity,
        shopify_customer_id=shopify_customer_id,
        display_name=display_name,
    )


def _thread_last_preview(conn, thread_id: Optional[str]) -> str:
    """The newest message-turn body on the thread (ADR-0079 queue preview)."""
    if not thread_id:
        return ""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT body FROM message_turn WHERE customer_thread_id = %s"
            " ORDER BY created_at DESC LIMIT 1",
            (thread_id,),
        )
        row = cur.fetchone()
    return (row[0] if row else "") or ""


def _thread_sms_active(conn, thread_id: Optional[str]) -> bool:
    """True while an unexpired SMS Session exists (ADR-0019/0083 governed-send gate)."""
    if not thread_id:
        return False
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM sms_session WHERE customer_thread_id = %s"
            " AND expires_at > now() LIMIT 1",
            (thread_id,),
        )
        return cur.fetchone() is not None


def _thread_messages(
    conn, thread_id: Optional[str], channel: str
) -> list[dict[str, Any]]:
    """The ordered Case Thread Context timeline for a thread (ADR-0082).

    ``message_turn`` has no channel column (a thread is single-channel), so the
    case/thread channel is applied to each turn. ``active_case_segment`` is the
    inverse of ``auto_handled``: the active Human Intervention segment is the
    non-auto-handled turns, while prior Auto-Handled turns stay de-emphasized.
    """
    if not thread_id:
        return []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, customer_thread_id, author, body, auto_handled, created_at"
            " FROM message_turn WHERE customer_thread_id = %s ORDER BY created_at ASC",
            (thread_id,),
        )
        rows = cur.fetchall()
    messages: list[dict[str, Any]] = []
    for row in rows:
        msg = serialize_row(row)
        assert msg is not None  # fetched row is never None
        msg["channel"] = channel
        msg["active_case_segment"] = not bool(row.get("auto_handled"))
        messages.append(msg)
    return messages


def _read_model(conn, row: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Expand a base ``cases`` row into the full WorkbenchCase read model (ADR-0064/0115).

    Durable columns are returned JSON-safe as-is; the ADR-0082 UI-derived fields
    (identity_summary, last_message_preview, sms_session_active) are computed by
    joining the customer thread, its newest message turn, and any live SMS
    session, and ``urgent`` is derived from the urgency label.
    """
    out = serialize_row(row)
    if out is None:
        return None
    thread_id = row.get("customer_thread_id") if row else None
    out["case_id"] = out["id"]
    out["thread_id"] = thread_id or ""
    out["urgent"] = (out.get("urgency") or "") in _URGENT_URGENCIES
    out["identity_summary"] = _thread_identity_summary(conn, thread_id)
    out["last_message_preview"] = _thread_last_preview(conn, thread_id)
    out["sms_session_active"] = _thread_sms_active(conn, thread_id)
    return out


def _case_row(conn, case_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM cases WHERE id = %s", (case_id,))
        row = cur.fetchone()
    return _read_model(conn, row)


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
    account_id = _require_actor(context)
    with conn.cursor() as cur:
        # Atomic claim (ADR-0079): the conflict guard lives in the WHERE clause, not
        # a prior read, so two reps who both pre-read the same unassigned case can't
        # both win — the loser's UPDATE matches no row. ``assignee_account_id = %s``
        # keeps a self re-claim idempotent. store.ts claimCase moves an open case to
        # in_progress on claim; mirror it for API-path/queue parity (ADR-0079/0141).
        cur.execute(
            """
            UPDATE cases SET
                assignee_account_id = %s,
                status = CASE WHEN status = 'open' THEN 'in_progress' ELSE status END,
                last_activity_at = now()
            WHERE id = %s
              AND (assignee_account_id IS NULL OR assignee_account_id = %s)
            """,
            (account_id, case_id, account_id),
        )
        claimed = cur.rowcount == 1
    if not claimed:
        # rowcount 0: distinguish a missing case (not_found -> 404, store-path
        # CASE_NOT_FOUND parity) from one already held by another account
        # (conflict -> 409, no silent steal). The raise rolls back the unit of work
        # (PostgresDriver), so a denied claim leaves no mutation and no audit row.
        if _status(conn, case_id) is None:
            raise ToolDriverError("not_found", f"case {case_id} not found.")
        raise ToolDriverError(
            "conflict", f"case {case_id} is already held by another account."
        )
    insert_audit(
        conn,
        profile=context.profile,
        account_id=account_id,
        action="claim_case",
        target_type="case",
        target_id=case_id,
        details={"assignee_account_id": account_id},
    )
    # Return the fresh read model so the BFF renders the updated case without a
    # second get_case round-trip; keep the legacy keys for existing callers.
    return {"case_id": case_id, "claimed": True, "case": _case_row(conn, case_id)}


def _assign_case(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    case_id = _require_case_id(params)
    _require_actor(context)
    _ensure_exists(conn, case_id)
    assignee_id = read_string(params, "assignee_id", "assigneeId")
    if assignee_id is None:
        raise ToolDriverError("unexpected_error", "assignee_id is required.")
    with conn.cursor() as cur:
        # store.ts assignCase also moves an open case to in_progress (ADR-0079).
        cur.execute(
            """
            UPDATE cases SET
                assignee_account_id = %s,
                status = CASE WHEN status = 'open' THEN 'in_progress' ELSE status END,
                last_activity_at = now()
            WHERE id = %s
            """,
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
    return {
        "case_id": case_id,
        "assignee_id": assignee_id,
        "assigned": True,
        "case": _case_row(conn, case_id),
    }


def _update_priority(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    case_id = _require_case_id(params)
    _require_actor(context)
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
    return {
        "case_id": case_id,
        "priority": priority,
        "updated": True,
        "case": _case_row(conn, case_id),
    }


def _update_contact_reason(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    case_id = _require_case_id(params)
    _require_actor(context)
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
    return {
        "case_id": case_id,
        "contact_reason": contact_reason,
        "updated": True,
        "case": _case_row(conn, case_id),
    }


def _capture_textline_send(
    conversation_id: str,
    body: str,
    media_url: Optional[str],
) -> dict[str, Any]:
    """Outbound Textline capture: live REST when ``TEXTLINE_ACCESS_TOKEN`` is set, else mock."""
    token = (os.environ.get("TEXTLINE_ACCESS_TOKEN") or "").strip()
    if token:
        from hermes_runtime.textline_reply import (
            TextlineSendError,
            make_textline_reply_sender,
            resolve_textline_config,
        )

        try:
            send = make_textline_reply_sender(config=resolve_textline_config())
            send(conversation_id, body)
        except ValueError as exc:
            raise ToolDriverError("configuration_missing", str(exc)) from exc
        except TextlineSendError as exc:
            raise ToolDriverError("vendor_timeout", str(exc)) from exc
    return _send_message(
        TextlineMockData(),
        {
            "conversation_id": conversation_id,
            "body": body,
            "media_url": media_url,
        },
    )


def _auto_handled_outcome(
    conn, thread_id: str
) -> tuple[str, bool, str]:
    """Derive outcome, tool_failure, and tool_summary for an auto-handled thread."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT tool_failure, summary FROM cases
            WHERE customer_thread_id = %s
              AND contact_reason IS DISTINCT FROM 'sales_outreach'
            ORDER BY opened_at DESC LIMIT 1
            """,
            (thread_id,),
        )
        row = cur.fetchone()
    if row is None:
        return "auto_resolved", False, ""
    tool_failure = bool(row.get("tool_failure"))
    summary = (row.get("summary") or "").strip()
    tool_summary = summary or ("tool_failure" if tool_failure else "")
    return "escalated_to_case", tool_failure, tool_summary


def _build_auto_handled_record(
    conn,
    thread_id: str,
    *,
    include_timeline: bool,
) -> Optional[dict[str, Any]]:
    """Map a fully auto-handled customer thread onto the AutoHandledRecord read model."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM customer_thread WHERE id = %s", (thread_id,))
        thread = cur.fetchone()
        if thread is None:
            return None
        cur.execute(
            """
            SELECT bool_and(auto_handled) AS all_auto
            FROM message_turn WHERE customer_thread_id = %s
            """,
            (thread_id,),
        )
        agg = cur.fetchone()
    if agg is None or not agg.get("all_auto"):
        return None
    channel = thread.get("channel") or "sms"
    outcome, tool_failure, tool_summary = _auto_handled_outcome(conn, thread_id)
    record: dict[str, Any] = {
        "record_id": thread_id,
        "channel": channel,
        "identity_summary": _thread_identity_summary(conn, thread_id),
        "last_message_preview": _thread_last_preview(conn, thread_id),
        "last_activity_at": thread.get("last_interaction_at"),
        "outcome": outcome,
        "tool_summary": tool_summary,
        "tool_failure": tool_failure,
        "timeline": [],
        # ponytail: tool-call evidence lives in Hermes Native Memory only; empty until
        # a durable tool-call store lands in Postgres.
        "tool_calls": [],
    }
    if include_timeline:
        record["timeline"] = _thread_messages(conn, thread_id, channel)
    return record


def _list_auto_handled(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ct.id
            FROM customer_thread ct
            WHERE EXISTS (
                SELECT 1 FROM message_turn mt WHERE mt.customer_thread_id = ct.id
            )
            AND (
                SELECT bool_and(auto_handled) FROM message_turn mt
                WHERE mt.customer_thread_id = ct.id
            ) IS TRUE
            AND NOT EXISTS (
                SELECT 1 FROM cases c
                WHERE c.customer_thread_id = ct.id
                  AND c.contact_reason = 'sales_outreach'
            )
            ORDER BY ct.last_interaction_at DESC
            """
        )
        thread_ids = [row[0] for row in cur.fetchall()]
    records = [
        r
        for tid in thread_ids
        if (r := _build_auto_handled_record(conn, tid, include_timeline=False))
        is not None
    ]
    return {"records": records}


def _get_auto_handled(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    record_id = read_string(params, "record_id", "recordId")
    if record_id is None:
        raise ToolDriverError("unexpected_error", "record_id is required.")
    record = _build_auto_handled_record(conn, record_id, include_timeline=True)
    if record is None:
        return {"record": None}
    insert_audit(
        conn,
        profile=context.profile,
        account_id=context.user_id,
        action="audit_view",
        target_type="auto_handled",
        target_id=record_id,
        details={"record_id": record_id},
    )
    return {"record": record}


def _list_sales_outreach(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT * FROM cases WHERE contact_reason = 'sales_outreach'
            ORDER BY last_activity_at DESC
            """
        )
        rows = cur.fetchall()
    return {"cases": [_read_model(conn, row) for row in rows]}


def _get_sales_outreach(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    case_id = _require_case_id(params)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM cases WHERE id = %s AND contact_reason = 'sales_outreach'",
            (case_id,),
        )
        row = cur.fetchone()
    if row is None:
        return {"case": None}
    insert_audit(
        conn,
        profile=context.profile,
        account_id=context.user_id,
        action="audit_view",
        target_type="case",
        target_id=case_id,
        details={"case_id": case_id},
    )
    return {"case": _read_model(conn, row)}


def _active_sms_session_id(conn, thread_id: Optional[str]) -> Optional[str]:
    """The live (unexpired) SMS session on ``thread_id``, if any."""
    if not thread_id:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM sms_session WHERE customer_thread_id = %s"
            " AND expires_at > now() ORDER BY created_at DESC LIMIT 1",
            (thread_id,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _textline_conversation_id(sms_session_id: str) -> str:
    """Textline conversation UUID suffix on the gateway session key (ADR-0115).

    ``sms_session:{thread_id}:{textline_uuid}`` — same peel as
    :meth:`PostgresGatewayStore.load_context`.
    """
    return sms_session_id.rsplit(":", 1)[-1]


def _resolve_sms_session_id(
    conn, *, thread_id: Optional[str], case_session_id: Optional[str]
) -> Optional[str]:
    """Prefer the case-bound SMS session when still active, else the newest live one."""
    if case_session_id:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM sms_session WHERE id = %s AND expires_at > now()",
                (case_session_id,),
            )
            if cur.fetchone() is not None:
                return case_session_id
    return _active_sms_session_id(conn, thread_id)


def _send_textline_message(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    """Governed employee-confirmed Textline send (ADR-0083/0035 composite seam).

    Validates SMS-session + assignee gating, sends via Textline when
    ``TEXTLINE_ACCESS_TOKEN`` is set (else mock capture), mirrors a
    ``message_turn``, and appends a ``textline_send`` audit row atomically.
    """
    case_id = _require_case_id(params)
    actor = _require_actor(context)
    body = read_string(params, "body")
    if body is None:
        raise ToolDriverError("unexpected_error", "body is required.")
    media_url = read_string(params, "media_url", "mediaUrl")

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM cases WHERE id = %s", (case_id,))
        row = cur.fetchone()
    if row is None:
        raise ToolDriverError("not_found", f"case {case_id} not found.")

    thread_id = row.get("customer_thread_id")
    channel = row.get("channel") or ""
    assignee = row.get("assignee_account_id")
    if (
        channel != "sms"
        or assignee != actor
        or not _thread_sms_active(conn, thread_id)
    ):
        raise ToolDriverError(
            "policy_blocked", "case not eligible for Textline send"
        )

    session_id = _resolve_sms_session_id(
        conn,
        thread_id=thread_id,
        case_session_id=row.get("sms_session_id"),
    )
    if session_id is None:
        raise ToolDriverError(
            "policy_blocked", "case not eligible for Textline send"
        )

    conversation_id = _textline_conversation_id(session_id)
    sent = _capture_textline_send(conversation_id, body, media_url)

    turn_id = new_id("mt")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO message_turn
                (id, sms_session_id, customer_thread_id, direction, author, body,
                 auto_handled)
            VALUES (%s, %s, %s, 'outbound', 'workbench', %s, FALSE)
            """,
            (turn_id, session_id, thread_id, body),
        )
        cur.execute(
            "UPDATE cases SET last_activity_at = now() WHERE id = %s",
            (case_id,),
        )
    insert_audit(
        conn,
        profile=context.profile,
        account_id=actor,
        action="textline_send",
        target_type="case",
        target_id=case_id,
        details={"detail": body},
    )
    return {"message": sent}


def _resolve_case(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    case_id = _require_case_id(params)
    _require_actor(context)
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
    return {"case_id": case_id, "status": "resolved", "case": _case_row(conn, case_id)}


def _get_case(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    case_id = _require_case_id(params)
    # A missing case is a legitimate empty read, not a tool failure: return null
    # rather than fabricate or raise (ADR-0020).
    return {"case": _case_row(conn, case_id)}


def _get_thread(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    case_id = _require_case_id(params)
    case = _case_row(conn, case_id)
    # A missing case is a legitimate empty read (ADR-0020); return nulls and do
    # not audit a view of a case that does not exist.
    if case is None:
        return {"case": None, "messages": []}
    thread_id = case.get("thread_id")
    messages = _thread_messages(conn, thread_id or None, case.get("channel") or "sms")
    # ADR-0042/0082: opening or refreshing Case Thread Context writes a Workbench
    # Audit Log case_view entry in the same transaction as the read, recording the
    # customer thread identifier. A threadless case omits it rather than logging a
    # misleading empty string.
    insert_audit(
        conn,
        profile=context.profile,
        account_id=context.user_id,
        action="case_view",
        target_type="case",
        target_id=case_id,
        details={"customer_thread_id": thread_id} if thread_id else {},
    )
    return {"case": case, "messages": messages}


# Deterministic customer_thread key for an inbound SMS (mirrors
# postgres_gateway_store._thread_id -- no hashing, just the literal format).
def _sms_thread_id(from_phone: str) -> str:
    return f"customer_thread:textline:{from_phone}"


def _latest_case_id_for_thread(conn, thread_id: str) -> Optional[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM cases WHERE customer_thread_id = %s"
            " ORDER BY opened_at DESC LIMIT 1",
            (thread_id,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _get_thread_by_phone(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    """Simulator read-back (FR-9/S02): the BFF only knows the simulated
    from-phone it posted, not a case_id (the gateway's inbound webhook creates
    the case asynchronously). Resolve the case via the same deterministic
    customer_thread key the gateway store uses, then defer to ``_get_thread``
    so the response shape and the case_view audit stay identical either way.
    """
    from_phone = read_string(params, "from_phone", "fromPhone")
    if not from_phone:
        raise ToolDriverError("unexpected_error", "from_phone is required.")
    thread_id = _sms_thread_id(from_phone)
    case_id = _latest_case_id_for_thread(conn, thread_id)
    if case_id is None:
        return {"case": None, "messages": []}
    return _get_thread(conn, {"case_id": case_id}, context)


# Mirrors store.ts DEFAULT_STATUSES: resolved cases are hidden by default.
_DEFAULT_STATUSES = ("open", "in_progress")


def _list_cases(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    """Queue read that mirrors the in-memory GatewayStore (ADR-0141 parity).

    The BFF dispatches ``buildCaseListFilter`` ({statuses, assignee}); this must
    filter and sort exactly like ``store.ts`` ``listCases`` + ``queueCompare``:
    exclude ``sales_outreach`` (ADR-0050), keep only the requested statuses
    (default open/in_progress), apply the assignee mode, and order urgent-first,
    unassigned-before-assigned, oldest-open-first (ADR-0079). Doing it in SQL also
    avoids fetching the whole table just to drop most rows.
    """
    raw_statuses = params.get("statuses")
    statuses = (
        [s for s in raw_statuses if isinstance(s, str) and s]
        if isinstance(raw_statuses, list)
        else []
    )
    if not statuses:
        statuses = list(_DEFAULT_STATUSES)

    assignee = params.get("assignee")
    assignee = assignee if isinstance(assignee, dict) else None
    mode = read_string(assignee, "mode") if assignee else None
    account_id = read_string(assignee, "account_id", "accountId") if assignee else None

    # IS DISTINCT FROM keeps NULL/blank reasons (the store compares !== so only an
    # exact "sales_outreach" is dropped); = ANY filters the requested status set.
    where = ["contact_reason IS DISTINCT FROM 'sales_outreach'", "status = ANY(%s)"]
    args: list[Any] = [statuses]
    if mode == "mine":
        where.append("assignee_account_id = %s")
        args.append(account_id)
    elif mode == "unassigned":
        where.append("assignee_account_id IS NULL")
    elif mode == "mine_or_unassigned":
        where.append("(assignee_account_id IS NULL OR assignee_account_id = %s)")
        args.append(account_id)
    # mode in (None, "all") -> no assignee predicate, matching matchesAssignee.

    sql = (
        "SELECT * FROM cases WHERE "
        + " AND ".join(where)
        + " ORDER BY (COALESCE(urgency, '') IN ('urgent', 'high')) DESC,"
        " (assignee_account_id IS NOT NULL) ASC, opened_at ASC"
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()
    return {"cases": [_read_model(conn, row) for row in rows]}


def _get_audit_log(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    case_id = _require_case_id(params)
    # Join the actor's account so the entry carries actor_username (ADR-0029); the
    # audit row itself only stores account_id. A missing/unknown account leaves it
    # NULL, which the BFF maps to an empty string.
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT a.*, acct.username AS actor_username
            FROM workbench_audit_log a
            LEFT JOIN workbench_account acct ON acct.id = a.account_id
            WHERE a.target_type = 'case' AND a.target_id = %s
            ORDER BY a.created_at ASC
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
            "send_textline_message": _send_textline_message,
        },
        "toee_workbench_read": {
            "get_case": _get_case,
            "list_cases": _list_cases,
            "get_audit_log": _get_audit_log,
            "get_thread": _get_thread,
            "get_thread_by_phone": _get_thread_by_phone,
            "list_auto_handled": _list_auto_handled,
            "get_auto_handled": _get_auto_handled,
            "list_sales_outreach": _list_sales_outreach,
            "get_sales_outreach": _get_sales_outreach,
        },
    }
