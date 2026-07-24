"""0.0.4 S03 (ADR-0154, FR-1/2/4/NFR-2/5): Postgres-backed ``toee_feedback``.

``submit_interaction_review`` is the EXTERNAL mechanism: a supervisor's
pass/fail judgment on one Auto-Handled Interaction record or one
sales_outreach Follow-up Case, persisted through the governed dispatch path,
actor-attributed and append-only. THE central governance claim of this
module: a write with no framework-resolved acting employee persists nothing --
zero rows, zero audit rows, not just a policy_blocked response. Skip-if-no-DB
via the shared ``datastore`` fixture (ADR-0142).
"""

from __future__ import annotations

import pytest

from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext


def _submit(driver, *, profile="internal_copilot", user_id=None, **params):
    return execute_tool(
        tool="toee_feedback",
        action="submit_interaction_review",
        params=params,
        context=ToolExecutionContext(profile=profile, user_id=user_id),
        driver=driver,
    )


def _review_count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM interaction_review")
        return cur.fetchone()[0]


def _audit_count(conn, *, action: str = "interaction_review_submitted") -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM workbench_audit_log WHERE action = %s", (action,)
        )
        return cur.fetchone()[0]


# --- happy path: real row, read back directly from Postgres -------------------


def test_submit_interaction_review_persists_a_row(datastore) -> None:
    driver, conn, _ = datastore
    result = _submit(
        driver,
        user_id="acct_super_1",
        subject_kind="auto_handled_record",
        subject_id="rec_1",
        verdict="fail",
        reason_tags=["factual_error", "tool_misuse"],
        comment="Quoted the wrong SKU.",
    )
    assert result.ok
    review_id = result.data["id"]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT subject_kind, subject_id, verdict, reason_tags, comment, "
            "reviewer_account_id, created_at FROM interaction_review WHERE id = %s",
            (review_id,),
        )
        row = cur.fetchone()
    assert row is not None
    subject_kind, subject_id, verdict, reason_tags, comment, reviewer, created_at = row
    assert subject_kind == "auto_handled_record"
    assert subject_id == "rec_1"
    assert verdict == "fail"
    assert set(reason_tags) == {"factual_error", "tool_misuse"}
    assert comment == "Quoted the wrong SKU."
    assert reviewer == "acct_super_1"
    assert created_at is not None


def test_submit_interaction_review_pass_needs_no_tags(datastore) -> None:
    driver, conn, _ = datastore
    result = _submit(
        driver,
        user_id="acct_super_1",
        subject_kind="sales_outreach_case",
        subject_id="case_1",
        verdict="pass",
    )
    assert result.ok
    with conn.cursor() as cur:
        cur.execute(
            "SELECT verdict, reason_tags FROM interaction_review WHERE id = %s",
            (result.data["id"],),
        )
        verdict, reason_tags = cur.fetchone()
    assert verdict == "pass"
    assert reason_tags == []


def test_submit_interaction_review_writes_an_audit_row(datastore) -> None:
    driver, conn, _ = datastore
    result = _submit(
        driver,
        user_id="acct_super_1",
        subject_kind="auto_handled_record",
        subject_id="rec_5",
        verdict="pass",
    )
    assert result.ok

    with conn.cursor() as cur:
        cur.execute(
            "SELECT account_id, action, target_type, target_id "
            "FROM workbench_audit_log WHERE action = 'interaction_review_submitted'"
        )
        row = cur.fetchone()
    assert row is not None
    account_id, action, target_type, target_id = row
    assert account_id == "acct_super_1"
    assert action == "interaction_review_submitted"
    assert target_type == "auto_handled_record"
    assert target_id == "rec_5"


# --- append-only: two reviews by one reviewer -> two rows, latest wins on read -


def test_submit_interaction_review_is_append_only_and_latest_wins(datastore) -> None:
    driver, conn, _ = datastore
    first = _submit(
        driver,
        user_id="acct_super_1",
        subject_kind="auto_handled_record",
        subject_id="rec_1",
        verdict="pass",
    )
    second = _submit(
        driver,
        user_id="acct_super_1",
        subject_kind="auto_handled_record",
        subject_id="rec_1",
        verdict="fail",
        reason_tags=["tone_inappropriate"],
    )
    assert first.ok and second.ok
    assert first.data["id"] != second.data["id"]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM interaction_review "
            "WHERE subject_kind = 'auto_handled_record' AND subject_id = 'rec_1'"
        )
        assert cur.fetchone()[0] == 2

        # Latest-wins read (DISTINCT ON, mirrors integrations._latest_probes).
        cur.execute(
            """
            SELECT DISTINCT ON (subject_kind, subject_id) verdict
            FROM interaction_review
            WHERE subject_kind = 'auto_handled_record' AND subject_id = 'rec_1'
            ORDER BY subject_kind, subject_id, created_at DESC
            """
        )
        latest_verdict = cur.fetchone()[0]
    assert latest_verdict == "fail"


# --- THE governance test: no actor -> zero rows, zero audit rows --------------


def test_submit_interaction_review_with_no_actor_persists_nothing(datastore) -> None:
    driver, conn, _ = datastore
    result = _submit(
        driver,
        user_id=None,
        subject_kind="auto_handled_record",
        subject_id="rec_1",
        verdict="pass",
    )
    assert not result.ok
    assert result.error_class == "policy_blocked"
    assert _review_count(conn) == 0
    assert _audit_count(conn) == 0


def test_submit_interaction_review_is_policy_blocked_outside_internal_copilot(
    datastore,
) -> None:
    driver, conn, _ = datastore
    result = _submit(
        driver,
        profile="customer_service_external",
        user_id="acct_super_1",
        subject_kind="auto_handled_record",
        subject_id="rec_1",
        verdict="pass",
    )
    assert not result.ok
    assert result.error_class == "policy_blocked"
    assert _review_count(conn) == 0


# --- DB-level CHECK: the floor holds even if a handler bug skips validation ---


def test_db_check_rejects_fail_with_empty_tags_even_via_raw_sql(datastore) -> None:
    # Proves the CONSTRAINT itself, independent of the handler: a naive
    # `array_length(reason_tags, 1) >= 1` CHECK would silently PASS this insert,
    # because array_length('{}', 1) is NULL and `FALSE OR NULL` is NULL, which
    # Postgres does not treat as a violation. The migration's coalesce(...,0)
    # closes that hole -- verified here with a raw INSERT that never goes near
    # the Python handler, so a future handler regression can't hide it.
    _, conn, _ = datastore
    with conn.cursor() as cur:
        with pytest.raises(Exception):
            cur.execute(
                "INSERT INTO interaction_review "
                "(id, subject_kind, subject_id, verdict, reason_tags, reviewer_account_id) "
                "VALUES ('irev_raw', 'auto_handled_record', 'rec_1', 'fail', '{}', 'acct_x')"
            )
    conn.rollback()


# --- rejections persist nothing ------------------------------------------------


def test_submit_interaction_review_fail_without_tags_persists_nothing(datastore) -> None:
    driver, conn, _ = datastore
    result = _submit(
        driver,
        user_id="acct_super_1",
        subject_kind="auto_handled_record",
        subject_id="rec_1",
        verdict="fail",
    )
    assert not result.ok
    assert result.error_class == "unexpected_error"
    assert _review_count(conn) == 0


def test_submit_interaction_review_rejects_internal_tag_and_persists_nothing(
    datastore,
) -> None:
    driver, conn, _ = datastore
    result = _submit(
        driver,
        user_id="acct_super_1",
        subject_kind="auto_handled_record",
        subject_id="rec_1",
        verdict="fail",
        reason_tags=["wrong_tone"],  # internal (draft-rating) set, not external
    )
    assert not result.ok
    assert result.error_class == "unexpected_error"
    assert _review_count(conn) == 0


def test_submit_interaction_review_rejects_unknown_subject_kind_and_persists_nothing(
    datastore,
) -> None:
    driver, conn, _ = datastore
    result = _submit(
        driver,
        user_id="acct_super_1",
        subject_kind="conversation_thread",
        subject_id="thread_1",
        verdict="pass",
    )
    assert not result.ok
    assert result.error_class == "unexpected_error"
    assert _review_count(conn) == 0


# --- model-supplied reviewer cannot be forged ----------------------------------


def test_submit_interaction_review_reviewer_cannot_be_forged(datastore) -> None:
    driver, conn, _ = datastore
    result = _submit(
        driver,
        user_id="acct_real",
        subject_kind="auto_handled_record",
        subject_id="rec_1",
        verdict="pass",
        reviewer_account_id="acct_forged",
    )
    assert result.ok
    assert result.data["reviewer_account_id"] == "acct_real"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT reviewer_account_id FROM interaction_review WHERE id = %s",
            (result.data["id"],),
        )
        assert cur.fetchone()[0] == "acct_real"
