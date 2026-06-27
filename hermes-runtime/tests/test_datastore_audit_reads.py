"""Slice 35 / #38: Postgres-backed supervisor audit reads (auto-handled + sales outreach)."""

from __future__ import annotations

from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext


def _ctx(user_id: str = "acct_supervisor"):
    return ToolExecutionContext(profile="internal_copilot", user_id=user_id)


def _run(driver, action, params=None, context=None):
    return execute_tool(
        tool="toee_workbench_read",
        action=action,
        params=params or {},
        context=context or _ctx(),
        driver=driver,
    )


def _seed_auto_thread(conn, thread_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO customer_thread (id, channel, channel_identity, shopify_customer_id)"
            " VALUES (%s, 'sms', '+15559876543', 'cust_audit')",
            (thread_id,),
        )
        session_id = f"sess_{thread_id}"
        cur.execute(
            "INSERT INTO sms_session (id, customer_thread_id, expires_at)"
            " VALUES (%s, %s, now() + interval '1 hour')",
            (session_id, thread_id),
        )
        cur.execute(
            """
            INSERT INTO message_turn
                (id, sms_session_id, customer_thread_id, direction, author, body, auto_handled)
            VALUES (%s, %s, %s, 'inbound', 'customer', 'Where is my order?', TRUE),
                   (%s, %s, %s, 'outbound', 'hermes', 'It ships today.', TRUE)
            """,
            (
                f"mt_{thread_id}_1",
                session_id,
                thread_id,
                f"mt_{thread_id}_2",
                session_id,
                thread_id,
            ),
        )
    conn.commit()


def _seed_sales_case(conn, case_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO cases (id, channel, contact_reason, status, summary)
            VALUES (%s, 'sms', 'sales_outreach', 'open', 'SEO pitch')
            """,
            (case_id,),
        )
    conn.commit()


def test_list_auto_handled_returns_fully_auto_threads(datastore) -> None:
    driver, conn, _ = datastore
    thread_id = "thr_auto_audit"
    _seed_auto_thread(conn, thread_id)

    result = _run(driver, "list_auto_handled")
    assert result.ok
    ids = [r["record_id"] for r in result.data["records"]]
    assert thread_id in ids


def test_get_auto_handled_returns_detail_and_audit_view(datastore) -> None:
    driver, conn, _ = datastore
    thread_id = "thr_auto_detail"
    actor = "acct_supervisor"
    _seed_auto_thread(conn, thread_id)

    result = _run(
        driver,
        "get_auto_handled",
        {"record_id": thread_id},
        _ctx(actor),
    )
    assert result.ok
    record = result.data["record"]
    assert record["record_id"] == thread_id
    assert len(record["timeline"]) == 2

    with conn.cursor() as cur:
        cur.execute(
            "SELECT action FROM workbench_audit_log WHERE target_id = %s",
            (thread_id,),
        )
        actions = [row[0] for row in cur.fetchall()]
    assert "audit_view" in actions


def test_get_auto_handled_unknown_returns_null(datastore) -> None:
    driver, _, _ = datastore
    result = _run(driver, "get_auto_handled", {"record_id": "missing"})
    assert result.ok
    assert result.data["record"] is None


def test_list_sales_outreach_filters_contact_reason(datastore) -> None:
    driver, conn, _ = datastore
    case_id = "case_sales_audit"
    _seed_sales_case(conn, case_id)

    result = _run(driver, "list_sales_outreach")
    assert result.ok
    ids = [c["case_id"] for c in result.data["cases"]]
    assert case_id in ids
    assert all(c.get("contact_reason") == "sales_outreach" for c in result.data["cases"])


def test_get_sales_outreach_rejects_non_sales_case(datastore) -> None:
    driver, conn, _ = datastore
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO cases (id, channel, contact_reason, status)
            VALUES ('case_not_sales', 'sms', 'order_status', 'open')
            """
        )
    conn.commit()

    result = _run(driver, "get_sales_outreach", {"case_id": "case_not_sales"})
    assert result.ok
    assert result.data["case"] is None
