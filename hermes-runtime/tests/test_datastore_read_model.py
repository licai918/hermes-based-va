"""Slice 35 / #38: the datastore read model is the full WorkbenchCase shape.

The ``cases`` table stores the durable columns; ADR-0064/0115 UI-derived fields
(identitySummary, lastMessagePreview, smsSessionActive) are computed at read time
by joining the customer thread, its latest message turn, and any live SMS session.
``urgent`` is derived from the ``urgency`` column. These reads feed the BFF map +
runtime validation (ADR-0070/0141). Skip-if-no-DB via the shared ``datastore``
fixture (ADR-0142).
"""

from __future__ import annotations

from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext


def _ctx(profile: str = "internal_copilot", user_id: str | None = None):
    return ToolExecutionContext(profile=profile, user_id=user_id)


def _run(driver, tool, action, params=None, context=None):
    return execute_tool(
        tool=tool,
        action=action,
        params=params or {},
        context=context or _ctx(),
        driver=driver,
    )


def _seed_thread(
    conn,
    *,
    thread_id: str,
    channel: str = "sms",
    channel_identity: str = "+15551230000",
    shopify_customer_id: str | None = None,
    sms_active: bool = True,
    messages: tuple[tuple[str, str, bool], ...] = (),
) -> None:
    """Insert a customer thread, one SMS session, and ordered message turns."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO customer_thread (id, channel, channel_identity, shopify_customer_id)"
            " VALUES (%s, %s, %s, %s)",
            (thread_id, channel, channel_identity, shopify_customer_id),
        )
        session_id = f"sess_{thread_id}"
        expiry = "now() + interval '1 hour'" if sms_active else "now() - interval '1 hour'"
        cur.execute(
            f"INSERT INTO sms_session (id, customer_thread_id, expires_at)"
            f" VALUES (%s, %s, {expiry})",
            (session_id, thread_id),
        )
        for index, (author, body, auto) in enumerate(messages):
            cur.execute(
                "INSERT INTO message_turn"
                " (id, sms_session_id, customer_thread_id, direction, author, body,"
                " auto_handled, created_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, now() + (%s || ' seconds')::interval)",
                (
                    f"mt_{thread_id}_{index}",
                    session_id,
                    thread_id,
                    "inbound",
                    author,
                    body,
                    auto,
                    str(index),
                ),
            )
    conn.commit()


def _seed_case(
    conn,
    *,
    case_id: str,
    thread_id: str | None = None,
    channel: str = "sms",
    urgency: str | None = "normal",
    status: str = "open",
    contact_reason: str = "order_status",
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO cases (id, channel, customer_thread_id, contact_reason, urgency, status)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (case_id, channel, thread_id, contact_reason, urgency, status),
        )
    conn.commit()


def test_get_case_computes_full_read_model_from_thread(datastore) -> None:
    driver, conn, _ = datastore
    _seed_thread(
        conn,
        thread_id="thr_rm",
        channel_identity="+15558889999",
        shopify_customer_id="cust_900",
        sms_active=True,
        messages=(
            ("customer", "first message", True),
            ("hermes", "the latest reply", False),
        ),
    )
    _seed_case(conn, case_id="case_rm", thread_id="thr_rm", urgency="high")

    case = _run(driver, "toee_workbench_read", "get_case", {"case_id": "case_rm"}).data["case"]

    assert case["case_id"] == "case_rm"
    assert case["thread_id"] == "thr_rm"
    # urgency "high" derives urgent=true (ADR-0064 urgency column -> WorkbenchCase.urgent).
    assert case["urgent"] is True
    # identitySummary reflects the linked Shopify customer on the thread.
    assert case["identity_summary"] == "Verified: cust_900"
    # lastMessagePreview is the newest turn on the thread.
    assert case["last_message_preview"] == "the latest reply"
    # smsSessionActive is true while a live (unexpired) SMS session exists.
    assert case["sms_session_active"] is True


def test_get_case_without_thread_returns_safe_read_model(datastore) -> None:
    driver, _, _ = datastore
    # create_case leaves customer_thread_id NULL and urgency unset.
    case_id = _run(driver, "toee_case", "create_case", {"contact_reason": "x"}).data["case_id"]

    case = _run(driver, "toee_workbench_read", "get_case", {"case_id": case_id}).data["case"]

    assert case["thread_id"] == ""
    assert case["urgent"] is False
    assert case["identity_summary"] == ""
    assert case["last_message_preview"] == ""
    assert case["sms_session_active"] is False


def test_expired_session_is_not_active(datastore) -> None:
    driver, conn, _ = datastore
    _seed_thread(conn, thread_id="thr_exp", sms_active=False, messages=(("customer", "hi", False),))
    _seed_case(conn, case_id="case_exp", thread_id="thr_exp")

    case = _run(driver, "toee_workbench_read", "get_case", {"case_id": "case_exp"}).data["case"]
    assert case["sms_session_active"] is False
    assert case["last_message_preview"] == "hi"


def test_list_cases_carries_read_model_fields(datastore) -> None:
    driver, conn, _ = datastore
    _seed_thread(conn, thread_id="thr_l", channel_identity="+15550001111", messages=(("customer", "hello", False),))
    _seed_case(conn, case_id="case_l", thread_id="thr_l", urgency="urgent")

    listed = _run(driver, "toee_workbench_read", "list_cases", {}).data["cases"]
    found = next(c for c in listed if c["case_id"] == "case_l")
    assert found["urgent"] is True
    assert found["identity_summary"] == "+15550001111"
    assert found["last_message_preview"] == "hello"
    assert found["thread_id"] == "thr_l"


def test_get_audit_log_includes_actor_username(datastore) -> None:
    driver, conn, _ = datastore
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO workbench_account (id, username, password_hash, role)"
            " VALUES (%s, %s, %s, %s)",
            ("acct_jane", "jane", "x", "supervisor"),
        )
    conn.commit()
    case_id = _run(driver, "toee_case", "create_case", {"contact_reason": "x"}).data["case_id"]
    _run(
        driver,
        "toee_case_manage",
        "claim_case",
        {"case_id": case_id},
        _ctx(user_id="acct_jane"),
    )

    entries = _run(
        driver, "toee_workbench_read", "get_audit_log", {"case_id": case_id}
    ).data["entries"]
    claim = next(e for e in entries if e["action"] == "claim_case")
    assert claim["actor_username"] == "jane"
