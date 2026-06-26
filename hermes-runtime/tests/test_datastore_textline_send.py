"""Slice 35 / #42: Postgres-backed governed Textline send composite handler."""

from __future__ import annotations

from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext


def _ctx(user_id: str = "acct_rep"):
    return ToolExecutionContext(profile="internal_copilot", user_id=user_id)


def _run(driver, action, params, context=None):
    return execute_tool(
        tool="toee_case_manage",
        action=action,
        params=params,
        context=context or _ctx(),
        driver=driver,
    )


def _seed_thread(conn, thread_id: str, *, sms_active: bool = True) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO customer_thread (id, channel, channel_identity)"
            " VALUES (%s, 'sms', '+15551230000')",
            (thread_id,),
        )
        session_id = f"sess_{thread_id}"
        expiry = "now() + interval '1 hour'" if sms_active else "now() - interval '1 hour'"
        cur.execute(
            f"INSERT INTO sms_session (id, customer_thread_id, expires_at)"
            f" VALUES (%s, %s, {expiry})",
            (session_id, thread_id),
        )
    conn.commit()
    return session_id


def _seed_case(conn, case_id: str, thread_id: str, assignee: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO cases
                (id, channel, customer_thread_id, contact_reason, status, assignee_account_id)
            VALUES (%s, 'sms', %s, 'order_status', 'in_progress', %s)
            """,
            (case_id, thread_id, assignee),
        )
    conn.commit()


def test_send_textline_message_mirrors_turn_and_audit(datastore) -> None:
    driver, conn, _ = datastore
    thread_id = "thr_send"
    case_id = "case_send"
    actor = "acct_rep"
    _seed_thread(conn, thread_id)
    _seed_case(conn, case_id, thread_id, actor)

    result = _run(
        driver,
        "send_textline_message",
        {"case_id": case_id, "body": "Your tires arrive today."},
        _ctx(actor),
    )
    assert result.ok
    msg = result.data["message"]
    assert msg["conversation_id"] == thread_id
    assert msg["body"] == "Your tires arrive today."

    thread = execute_tool(
        tool="toee_workbench_read",
        action="get_thread",
        params={"case_id": case_id},
        context=_ctx(actor),
        driver=driver,
    )
    assert thread.ok
    bodies = [m["body"] for m in thread.data["messages"]]
    assert "Your tires arrive today." in bodies

    audit = execute_tool(
        tool="toee_workbench_read",
        action="get_audit_log",
        params={"case_id": case_id},
        context=_ctx(actor),
        driver=driver,
    )
    assert audit.ok
    actions = [e["action"] for e in audit.data["entries"]]
    assert "textline_send" in actions


def test_send_textline_message_denies_ineligible_case(datastore) -> None:
    driver, conn, _ = datastore
    thread_id = "thr_inelig"
    case_id = "case_inelig"
    _seed_thread(conn, thread_id, sms_active=False)
    _seed_case(conn, case_id, thread_id, "acct_rep")

    result = _run(
        driver,
        "send_textline_message",
        {"case_id": case_id, "body": "hello"},
        _ctx("acct_rep"),
    )
    assert not result.ok
    assert result.error_class == "policy_blocked"
