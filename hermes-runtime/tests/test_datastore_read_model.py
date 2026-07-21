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
    assignee_account_id: str | None = None,
    opened_offset: int = 0,
) -> None:
    # opened_offset shifts opened_at off now() so the ADR-0079 oldest-first
    # tiebreak is deterministic regardless of insert timing.
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO cases"
            " (id, channel, customer_thread_id, contact_reason, urgency, status,"
            " assignee_account_id, opened_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, now() + (%s || ' seconds')::interval)",
            (
                case_id,
                channel,
                thread_id,
                contact_reason,
                urgency,
                status,
                assignee_account_id,
                str(opened_offset),
            ),
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
    assert case["identity_summary"] == "Verified: cust_900 · +1 (555) 888-9999"
    # lastMessagePreview is the newest turn on the thread.
    assert case["last_message_preview"] == "the latest reply"
    # smsSessionActive is true while a live (unexpired) SMS session exists.
    assert case["sms_session_active"] is True


def test_identity_summary_uses_snapshot_display_name_with_gid(datastore) -> None:
    driver, conn, _ = datastore
    _seed_thread(
        conn,
        thread_id="thr_snap",
        channel_identity="+17786803250",
        shopify_customer_id="gid://shopify/Customer/1019382595648",
        messages=(("customer", "hi", False),),
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO session_identity_snapshot
                (id, event_id, channel, channel_identity, match_result)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            """,
            (
                "snap_thr_snap",
                "evt_thr_snap",
                "sms",
                "+17786803250",
                '{"outcome": "verified_customer", "shopify_customer_id":'
                ' "gid://shopify/Customer/1019382595648",'
                ' "company_name": "Hello"}',
            ),
        )
    conn.commit()
    _seed_case(conn, case_id="case_snap", thread_id="thr_snap")

    case = _run(driver, "toee_workbench_read", "get_case", {"case_id": "case_snap"}).data["case"]
    assert case["identity_summary"] == "Verified: Hello · +1 (778) 680-3250"


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
    assert found["identity_summary"] == "+1 (555) 000-1111"
    assert found["last_message_preview"] == "hello"
    assert found["thread_id"] == "thr_l"


def test_list_cases_honors_queue_filter_and_adr0079_sort(datastore) -> None:
    """C1: the API path must filter + sort exactly like the in-memory store.

    The BFF dispatches ``buildCaseListFilter`` ({statuses, assignee}); the
    datastore must exclude sales_outreach (ADR-0050) and out-of-status/other-rep
    cases, then order urgent-first, unassigned-before-assigned, oldest-first
    (ADR-0079) — byte-for-byte with store.ts listCases + queueCompare.
    """
    driver, conn, _ = datastore
    rep_a, rep_b = "acct_rep_a", "acct_rep_b"
    # Survivors of the rep-A queue, listed in their expected output order:
    _seed_case(conn, case_id="case_urgent", urgency="urgent", opened_offset=0)
    _seed_case(conn, case_id="case_norm_unassigned_old", urgency="normal", opened_offset=10)
    _seed_case(conn, case_id="case_norm_unassigned_new", urgency="normal", opened_offset=40)
    _seed_case(
        conn, case_id="case_norm_rep_a", urgency="normal",
        assignee_account_id=rep_a, opened_offset=20,
    )
    # Excluded: rep B's case, a resolved case, and a sales_outreach case.
    _seed_case(
        conn, case_id="case_rep_b", urgency="normal",
        assignee_account_id=rep_b, opened_offset=5,
    )
    _seed_case(conn, case_id="case_resolved", urgency="normal", status="resolved", opened_offset=1)
    _seed_case(
        conn, case_id="case_sales", urgency="urgent",
        contact_reason="sales_outreach", opened_offset=2,
    )

    listed = _run(
        driver,
        "toee_workbench_read",
        "list_cases",
        {
            "statuses": ["open", "in_progress"],
            "assignee": {"mode": "mine_or_unassigned", "accountId": rep_a},
        },
    ).data["cases"]

    assert [c["case_id"] for c in listed] == [
        "case_urgent",  # urgent tier first
        "case_norm_unassigned_old",  # then unassigned-before-assigned, oldest first
        "case_norm_unassigned_new",  # (newer unassigned still beats the assigned one)
        "case_norm_rep_a",  # assigned-to-me sorts last in its tier
    ]


def test_get_thread_returns_timeline_with_derived_channel_and_segment(datastore) -> None:
    driver, conn, _ = datastore
    _seed_thread(
        conn,
        thread_id="thr_t",
        channel="sms",
        messages=(
            ("customer", "older auto-handled", True),
            ("hermes", "active human reply", False),
        ),
    )
    _seed_case(conn, case_id="case_t", thread_id="thr_t", channel="sms")

    result = _run(driver, "toee_workbench_read", "get_thread", {"case_id": "case_t"}).data

    assert result["case"]["case_id"] == "case_t"
    messages = result["messages"]
    assert [m["body"] for m in messages] == ["older auto-handled", "active human reply"]
    # message_turn has no channel column; it is derived from the case/thread.
    assert all(m["channel"] == "sms" for m in messages)
    # ADR-0082 highlight: the active Human Intervention segment is the
    # non-auto-handled turns; prior Auto-Handled turns stay de-emphasized.
    assert messages[0]["auto_handled"] is True
    assert messages[0]["active_case_segment"] is False
    assert messages[1]["auto_handled"] is False
    assert messages[1]["active_case_segment"] is True


def test_get_thread_writes_one_case_view_audit_entry(datastore) -> None:
    driver, conn, _ = datastore
    _seed_thread(conn, thread_id="thr_av", messages=(("customer", "hi", False),))
    _seed_case(conn, case_id="case_av", thread_id="thr_av")

    _run(
        driver,
        "toee_workbench_read",
        "get_thread",
        {"case_id": "case_av"},
        _ctx(user_id="acct_z"),
    )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT action, target_type, target_id, account_id, details"
            " FROM workbench_audit_log WHERE target_id = %s",
            ("case_av",),
        )
        rows = cur.fetchall()
    # ADR-0042: opening Case Thread Context writes exactly one case_view entry that
    # records the viewer, the case, and the customer thread identifier.
    assert rows == [
        ("case_view", "case", "case_av", "acct_z", {"customer_thread_id": "thr_av"})
    ]


def test_get_thread_missing_case_is_empty_read_without_audit(datastore) -> None:
    driver, conn, _ = datastore
    result = _run(driver, "toee_workbench_read", "get_thread", {"case_id": "nope"}).data
    # A missing case is a legitimate empty read (ADR-0020), not a fabricated view,
    # so nothing is audited.
    assert result == {"case": None, "messages": []}
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM workbench_audit_log")
        assert cur.fetchone()[0] == 0


def test_get_thread_threadless_case_has_empty_timeline(datastore) -> None:
    driver, conn, _ = datastore
    case_id = _run(
        driver, "toee_case", "create_case", {"contact_reason": "x"}
    ).data["case_id"]

    result = _run(driver, "toee_workbench_read", "get_thread", {"case_id": case_id}).data

    assert result["case"]["case_id"] == case_id
    assert result["messages"] == []
    # ADR-0042: a threadless case still audits the view, but omits the thread id
    # rather than writing a misleading empty string.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT details FROM workbench_audit_log WHERE target_id = %s", (case_id,)
        )
        assert cur.fetchone()[0] == {}


def test_get_thread_by_phone_resolves_case_from_deterministic_thread_key(datastore) -> None:
    """S02 (FR-9): the simulator BFF only knows the from-phone it posted, not a
    case_id -- the gateway's inbound webhook creates the case asynchronously.
    get_thread_by_phone must resolve the same customer_thread key the gateway
    store derives (``customer_thread:textline:{from_phone}``) and return the
    identical shape as get_thread by case_id.
    """
    driver, conn, _ = datastore
    thread_id = "customer_thread:textline:+15551234567"
    _seed_thread(
        conn,
        thread_id=thread_id,
        channel_identity="+15551234567",
        messages=(
            ("customer", "do you have 225/65R17?", False),
            ("hermes", "yes, in stock", False),
        ),
    )
    _seed_case(conn, case_id="case_phone", thread_id=thread_id)

    result = _run(
        driver, "toee_workbench_read", "get_thread_by_phone", {"from_phone": "+15551234567"}
    ).data

    assert result["case"]["case_id"] == "case_phone"
    assert [m["body"] for m in result["messages"]] == [
        "do you have 225/65R17?",
        "yes, in stock",
    ]


def test_get_thread_by_phone_unknown_number_is_empty_read(datastore) -> None:
    driver, _, _ = datastore
    # A phone that never sent an inbound turn has no customer_thread/case row
    # (ADR-0020 empty read), same contract as get_thread's missing-case path.
    result = _run(
        driver, "toee_workbench_read", "get_thread_by_phone", {"from_phone": "+19995550000"}
    ).data
    assert result == {"case": None, "messages": []}


def test_get_thread_by_email_resolves_a_thread_s17_store_actually_wrote(datastore) -> None:
    """S18 (FR-11) CRITICAL key-match proof: get_thread_by_email must resolve
    the SAME customer_thread key S17's PostgresGatewayStore derives for a real
    inbound email (customer_thread:email:{canonicalize_email(addr)}).

    Rather than hand-seeding a row under the "expected" key (which would only
    prove the test author's guess, not the real write path), this writes
    through the actual gateway store -- the same one hermes-runtime's
    /webhooks/simulated-email route uses -- via persist_accepted_inbound, then
    reads it back through the datastore handler. A mixed-case From address
    proves canonicalize_email is applied identically on both sides: a
    different (even correct-looking) canonicalization on the read side would
    silently return an empty read instead of failing loudly.
    """
    from hermes_runtime.postgres_gateway_store import PostgresGatewayStore
    from toee_hermes.gateway.ingress import SessionIdentitySnapshot
    from toee_hermes.gateway.normalize import to_inbound_email_event
    from toee_hermes.gateway.pipeline import InboundDecision

    driver, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)

    event = to_inbound_email_event(
        event_id="evt-email-readback",
        conversation_id="conv-email-readback",
        from_address="Accounts@Acme-Fleet.EXAMPLE",
        subject="Order 10444",
        body="Where is my order?",
        received_at="2026-01-01T00:00:00Z",
    )
    snapshot = SessionIdentitySnapshot(
        outcome="unmatched_caller", resolved_at="2026-01-01T00:00:00Z"
    )
    decision = InboundDecision(
        status=200, action="enqueue", stage="accept", event=event, snapshot=snapshot
    )
    context, created = store.persist_accepted_inbound(decision)
    assert created is True
    store.persist_agent_outbound(context, "Your order ships tomorrow.")

    result = _run(
        driver,
        "toee_workbench_read",
        "get_thread_by_email",
        {"from_address": "accounts@acme-fleet.example"},
    ).data

    assert result["case"] is not None
    assert [m["body"] for m in result["messages"]] == [
        "Subject: Order 10444\n\nWhere is my order?",
        "Your order ships tomorrow.",
    ]


def test_get_thread_by_email_unknown_address_is_empty_read(datastore) -> None:
    driver, _, _ = datastore
    # An address that never sent an inbound email has no customer_thread/case
    # row (ADR-0020 empty read), same contract as get_thread_by_phone's.
    result = _run(
        driver,
        "toee_workbench_read",
        "get_thread_by_email",
        {"from_address": "nobody@nowhere.example"},
    ).data
    assert result == {"case": None, "messages": []}


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
