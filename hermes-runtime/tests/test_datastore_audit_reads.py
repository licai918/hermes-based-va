"""Slice 35 / #38: Postgres-backed supervisor audit reads (auto-handled + sales outreach)."""

from __future__ import annotations

import pytest

from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext


@pytest.fixture(autouse=True)
def _seed_reviewing_account(datastore):
    """FR-4's role gate (``hermes_runtime/datastore/handlers/feedback.py``)
    requires ``submit_interaction_review``'s actor to be a supervisor/admin
    ``workbench_account`` row. ``_submit_review`` below hardcodes
    "acct_super_1" as that actor across this file's reviewed-flag tests --
    seed it once here rather than at every call site.
    """
    _, conn, _ = datastore
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO workbench_account (id, username, password_hash, role) "
            "VALUES ('acct_super_1', 'acct_super_1', 'x', 'workbench_supervisor')"
        )
    conn.commit()


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


# --- S05 (FR-6): the list read surfaces a per-row "reviewed" flag ------------


def _submit_review(driver, *, subject_kind: str, subject_id: str, verdict: str = "pass", **params):
    return execute_tool(
        tool="toee_feedback",
        action="submit_interaction_review",
        params={
            "subject_kind": subject_kind,
            "subject_id": subject_id,
            "verdict": verdict,
            **params,
        },
        context=ToolExecutionContext(profile="internal_copilot", user_id="acct_super_1"),
        driver=driver,
    )


def test_list_auto_handled_marks_a_never_reviewed_record_not_reviewed(datastore) -> None:
    driver, conn, _ = datastore
    thread_id = "thr_auto_unreviewed"
    _seed_auto_thread(conn, thread_id)

    result = _run(driver, "list_auto_handled")
    assert result.ok
    row = next(r for r in result.data["records"] if r["record_id"] == thread_id)
    assert row["reviewed"] is False


def test_list_auto_handled_marks_a_reviewed_record_reviewed(datastore) -> None:
    driver, conn, _ = datastore
    thread_id = "thr_auto_reviewed"
    _seed_auto_thread(conn, thread_id)

    review = _submit_review(
        driver, subject_kind="auto_handled_record", subject_id=thread_id
    )
    assert review.ok

    result = _run(driver, "list_auto_handled")
    assert result.ok
    row = next(r for r in result.data["records"] if r["record_id"] == thread_id)
    assert row["reviewed"] is True


def test_list_auto_handled_stays_reviewed_after_a_second_appended_review(
    datastore,
) -> None:
    driver, conn, _ = datastore
    thread_id = "thr_auto_re_reviewed"
    _seed_auto_thread(conn, thread_id)

    first = _submit_review(
        driver, subject_kind="auto_handled_record", subject_id=thread_id, verdict="pass"
    )
    second = _submit_review(
        driver,
        subject_kind="auto_handled_record",
        subject_id=thread_id,
        verdict="fail",
        reason_tags=["factual_error"],
    )
    assert first.ok and second.ok

    result = _run(driver, "list_auto_handled")
    assert result.ok
    row = next(r for r in result.data["records"] if r["record_id"] == thread_id)
    assert row["reviewed"] is True


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


def test_list_sales_outreach_marks_a_never_reviewed_case_not_reviewed(datastore) -> None:
    driver, conn, _ = datastore
    case_id = "case_sales_unreviewed"
    _seed_sales_case(conn, case_id)

    result = _run(driver, "list_sales_outreach")
    assert result.ok
    row = next(c for c in result.data["cases"] if c["case_id"] == case_id)
    assert row["reviewed"] is False


def test_list_sales_outreach_marks_a_reviewed_case_reviewed(datastore) -> None:
    driver, conn, _ = datastore
    case_id = "case_sales_reviewed"
    _seed_sales_case(conn, case_id)

    review = _submit_review(
        driver, subject_kind="sales_outreach_case", subject_id=case_id
    )
    assert review.ok

    result = _run(driver, "list_sales_outreach")
    assert result.ok
    row = next(c for c in result.data["cases"] if c["case_id"] == case_id)
    assert row["reviewed"] is True


def test_list_sales_outreach_stays_reviewed_after_a_second_appended_review(
    datastore,
) -> None:
    driver, conn, _ = datastore
    case_id = "case_sales_re_reviewed"
    _seed_sales_case(conn, case_id)

    first = _submit_review(
        driver, subject_kind="sales_outreach_case", subject_id=case_id, verdict="pass"
    )
    second = _submit_review(
        driver,
        subject_kind="sales_outreach_case",
        subject_id=case_id,
        verdict="fail",
        reason_tags=["factual_error"],
    )
    assert first.ok and second.ok

    result = _run(driver, "list_sales_outreach")
    assert result.ok
    row = next(c for c in result.data["cases"] if c["case_id"] == case_id)
    assert row["reviewed"] is True


def test_list_sales_outreach_does_not_leak_review_across_unrelated_sibling(
    datastore,
) -> None:
    """An unsampled sibling case stays Not reviewed even when another case in the
    same list has been reviewed (PAC-2, S05 brief) -- proves the join is keyed
    per subject_id, not a blanket "any review exists anywhere" flag.
    """
    driver, conn, _ = datastore
    reviewed_case = "case_sales_sibling_reviewed"
    sibling_case = "case_sales_sibling_untouched"
    _seed_sales_case(conn, reviewed_case)
    _seed_sales_case(conn, sibling_case)

    review = _submit_review(
        driver, subject_kind="sales_outreach_case", subject_id=reviewed_case
    )
    assert review.ok

    result = _run(driver, "list_sales_outreach")
    assert result.ok
    by_id = {c["case_id"]: c["reviewed"] for c in result.data["cases"]}
    assert by_id[reviewed_case] is True
    assert by_id[sibling_case] is False


# --- US-7 (FR-5): the audit detail read surfaces the CURRENT ACCOUNT's own ---
# --- latest review, so reopening a record shows the prior verdict. ----------


def _seed_second_reviewer(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO workbench_account (id, username, password_hash, role) "
            "VALUES ('acct_super_2', 'acct_super_2', 'x', 'workbench_supervisor')"
        )
    conn.commit()


def test_get_auto_handled_with_no_review_reads_no_prior_review(datastore) -> None:
    driver, conn, _ = datastore
    thread_id = "thr_auto_my_review_none"
    _seed_auto_thread(conn, thread_id)

    result = _run(driver, "get_auto_handled", {"record_id": thread_id}, _ctx("acct_super_1"))
    assert result.ok
    assert result.data["record"]["my_review"] is None


def test_get_auto_handled_reads_back_own_review_verdict_tags_comment(datastore) -> None:
    driver, conn, _ = datastore
    thread_id = "thr_auto_my_review_present"
    _seed_auto_thread(conn, thread_id)

    review = _submit_review(
        driver,
        subject_kind="auto_handled_record",
        subject_id=thread_id,
        verdict="fail",
        reason_tags=["factual_error", "tone_inappropriate"],
        comment="gave the wrong ETA",
    )
    assert review.ok

    result = _run(driver, "get_auto_handled", {"record_id": thread_id}, _ctx("acct_super_1"))
    assert result.ok
    my_review = result.data["record"]["my_review"]
    assert my_review is not None
    assert my_review["verdict"] == "fail"
    assert my_review["reason_tags"] == ["factual_error", "tone_inappropriate"]
    assert my_review["comment"] == "gave the wrong ETA"
    assert my_review["reviewer_account_id"] == "acct_super_1"


def test_get_auto_handled_my_review_is_the_latest_of_two_appended_reviews(
    datastore,
) -> None:
    driver, conn, _ = datastore
    thread_id = "thr_auto_my_review_latest"
    _seed_auto_thread(conn, thread_id)

    first = _submit_review(
        driver, subject_kind="auto_handled_record", subject_id=thread_id, verdict="pass"
    )
    second = _submit_review(
        driver,
        subject_kind="auto_handled_record",
        subject_id=thread_id,
        verdict="fail",
        reason_tags=["should_have_escalated"],
    )
    assert first.ok and second.ok

    result = _run(driver, "get_auto_handled", {"record_id": thread_id}, _ctx("acct_super_1"))
    assert result.ok
    my_review = result.data["record"]["my_review"]
    assert my_review["verdict"] == "fail"
    assert my_review["reason_tags"] == ["should_have_escalated"]


def test_get_auto_handled_review_by_a_different_account_is_not_mine(datastore) -> None:
    driver, conn, _ = datastore
    thread_id = "thr_auto_my_review_not_mine"
    _seed_auto_thread(conn, thread_id)
    _seed_second_reviewer(conn)

    review = _submit_review(
        driver, subject_kind="auto_handled_record", subject_id=thread_id, verdict="pass"
    )
    assert review.ok

    result = _run(driver, "get_auto_handled", {"record_id": thread_id}, _ctx("acct_super_2"))
    assert result.ok
    assert result.data["record"]["my_review"] is None


def test_get_sales_outreach_reads_back_own_review(datastore) -> None:
    driver, conn, _ = datastore
    case_id = "case_sales_my_review_present"
    _seed_sales_case(conn, case_id)

    review = _submit_review(
        driver,
        subject_kind="sales_outreach_case",
        subject_id=case_id,
        verdict="fail",
        reason_tags=["policy_violation"],
        comment="pitched a discontinued SKU",
    )
    assert review.ok

    result = _run(driver, "get_sales_outreach", {"case_id": case_id}, _ctx("acct_super_1"))
    assert result.ok
    my_review = result.data["case"]["my_review"]
    assert my_review is not None
    assert my_review["verdict"] == "fail"
    assert my_review["comment"] == "pitched a discontinued SKU"


def test_get_sales_outreach_with_no_review_reads_no_prior_review(datastore) -> None:
    driver, conn, _ = datastore
    case_id = "case_sales_my_review_none"
    _seed_sales_case(conn, case_id)

    result = _run(driver, "get_sales_outreach", {"case_id": case_id}, _ctx("acct_super_1"))
    assert result.ok
    assert result.data["case"]["my_review"] is None


def test_get_sales_outreach_review_by_a_different_account_is_not_mine(datastore) -> None:
    driver, conn, _ = datastore
    case_id = "case_sales_my_review_not_mine"
    _seed_sales_case(conn, case_id)
    _seed_second_reviewer(conn)

    review = _submit_review(
        driver, subject_kind="sales_outreach_case", subject_id=case_id, verdict="pass"
    )
    assert review.ok

    result = _run(driver, "get_sales_outreach", {"case_id": case_id}, _ctx("acct_super_2"))
    assert result.ok
    assert result.data["case"]["my_review"] is None


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


def test_list_auto_handled_result_is_json_serializable(datastore) -> None:
    """The dispatch server JSON-encodes every tool result, so a raw ``datetime``
    in the record is a hard HTTP 500 -- not a governed error, an unhandled
    exception.

    This escaped every prior test because they assert on the Python dict, which
    holds a ``datetime`` happily, and because a fresh dev DB has NO auto-handled
    records at all (the list is empty, so nothing ever serialized). It only
    fires once a real fully-auto thread exists -- found by driving the live
    stack. ``json.dumps`` is exactly what the server does.
    """
    import json

    driver, conn, _ = datastore
    _seed_auto_thread(conn, "thread_json_safe")

    result = _run(driver, "list_auto_handled")
    assert result.ok
    assert result.data["records"], "expected the seeded auto-handled record"
    json.dumps(result.data)  # raises TypeError if any field is not JSON-safe
