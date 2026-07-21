"""Slice 35 / #42: Postgres-backed governed SMS send composite handler."""

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


def _seed_thread(
    conn,
    thread_id: str,
    *,
    sms_active: bool = True,
    sms_conversation_id: str = "7931e83f-96d9-4070-9ca4-081bcf36afd0",
) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO customer_thread (id, channel, channel_identity)"
            " VALUES (%s, 'sms', '+15551230000')",
            (thread_id,),
        )
        session_id = f"sms_session:{thread_id}:{sms_conversation_id}"
        expiry = "now() + interval '1 hour'" if sms_active else "now() - interval '1 hour'"
        cur.execute(
            f"INSERT INTO sms_session (id, customer_thread_id, expires_at)"
            f" VALUES (%s, %s, {expiry})",
            (session_id, thread_id),
        )
    conn.commit()
    return session_id


def _seed_case(conn, case_id: str, thread_id: str, assignee: str, session_id: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO cases
                (id, channel, customer_thread_id, sms_session_id, contact_reason, status, assignee_account_id)
            VALUES (%s, 'sms', %s, %s, 'order_status', 'in_progress', %s)
            """,
            (case_id, thread_id, session_id, assignee),
        )
    conn.commit()


def test_send_sms_message_mirrors_turn_and_audit(datastore) -> None:
    driver, conn, _ = datastore
    thread_id = "thr_send"
    case_id = "case_send"
    actor = "acct_rep"
    session_id = _seed_thread(conn, thread_id)
    _seed_case(conn, case_id, thread_id, actor, session_id)

    result = _run(
        driver,
        "send_sms_message",
        {"case_id": case_id, "body": "Your tires arrive today."},
        _ctx(actor),
    )
    assert result.ok
    msg = result.data["message"]
    assert msg["conversation_id"] == "7931e83f-96d9-4070-9ca4-081bcf36afd0"
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
    assert "sms_send" in actions


def test_send_sms_message_denies_ineligible_case(datastore) -> None:
    driver, conn, _ = datastore
    thread_id = "thr_inelig"
    case_id = "case_inelig"
    session_id = _seed_thread(conn, thread_id, sms_active=False)
    _seed_case(conn, case_id, thread_id, "acct_rep", session_id)

    result = _run(
        driver,
        "send_sms_message",
        {"case_id": case_id, "body": "hello"},
        _ctx("acct_rep"),
    )
    assert not result.ok
    assert result.error_class == "policy_blocked"


def test_send_sms_message_prefers_case_bound_session(datastore) -> None:
    """When several SMS sessions are live, reply on the case-bound conversation."""
    driver, conn, _ = datastore
    thread_id = "thr_multi_sess"
    case_id = "case_multi_sess"
    real_conv = "7931e83f-96d9-4070-9ca4-081bcf36afd0"
    case_session = _seed_thread(
        conn, thread_id, sms_conversation_id=real_conv
    )
    # A newer active session on the same thread (legacy simulate id) must not win.
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sms_session (id, customer_thread_id, expires_at)"
            " VALUES (%s, %s, now() + interval '1 hour')",
            (
                f"sms_session:{thread_id}:conv-newer-fake",
                thread_id,
            ),
        )
    conn.commit()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO cases
                (id, channel, customer_thread_id, sms_session_id, contact_reason,
                 status, assignee_account_id)
            VALUES (%s, 'sms', %s, %s, 'order_status', 'in_progress', %s)
            """,
            (case_id, thread_id, case_session, "acct_rep"),
        )
    conn.commit()

    result = _run(
        driver,
        "send_sms_message",
        {"case_id": case_id, "body": "Bound session reply."},
        _ctx("acct_rep"),
    )
    assert result.ok
    assert result.data["message"]["conversation_id"] == real_conv


def test_send_sms_message_live_when_api_token_set(datastore, monkeypatch) -> None:
    """When SIMPLETEXTING_API_TOKEN is set, the composite handler POSTs to SimpleTexting."""
    driver, conn, _ = datastore
    thread_id = "thr_live"
    case_id = "case_live"
    actor = "acct_rep"
    # SimpleTexting sessions key the conversation by contact phone (ADR-0115 peel).
    session_id = _seed_thread(conn, thread_id, sms_conversation_id="+15551230000")
    _seed_case(conn, case_id, thread_id, actor, session_id)

    posts: list[tuple[str, dict, bytes]] = []

    def fake_post(*, url: str, headers: dict, body: bytes) -> int:
        posts.append((url, headers, body))
        return 201

    monkeypatch.setenv("SIMPLETEXTING_API_TOKEN", "test-api-token")
    monkeypatch.setattr("hermes_runtime.simpletexting_reply._urllib_post", fake_post)

    result = _run(
        driver,
        "send_sms_message",
        {"case_id": case_id, "body": "Live outbound."},
        _ctx(actor),
    )
    assert result.ok
    assert len(posts) == 1
    assert posts[0][0].endswith("/api/messages")
    assert posts[0][1]["Authorization"] == "Bearer test-api-token"
    assert b'"contactPhone": "15551230000"' in posts[0][2]
    assert b"Live outbound." in posts[0][2]
