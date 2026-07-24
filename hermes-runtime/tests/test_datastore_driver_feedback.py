"""0.0.4 S03/S06 (ADR-0154, FR-1/2/4/NFR-2/5): Postgres-backed ``toee_feedback``.

``submit_interaction_review`` is the EXTERNAL mechanism: a supervisor's
pass/fail judgment on one Auto-Handled Interaction record or one
sales_outreach Follow-up Case, persisted through the governed dispatch path,
actor-attributed and append-only. THE central governance claim of this
module: a write with no framework-resolved acting employee persists nothing --
zero rows, zero audit rows, not just a policy_blocked response.

``submit_draft_rating`` (S06) is the INTERNAL mechanism: a rep's thumbs-up/
down on one Copilot Draft Action draft, PLUS a case-ownership gate (the acting
rep must hold the case). Skip-if-no-DB via the shared ``datastore`` fixture
(ADR-0142).
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


# --- submit_draft_rating (S06): the INTERNAL mechanism -------------------------


def _insert_case(conn, *, case_id: str, assignee_account_id: str | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO cases (id, channel, assignee_account_id) "
            "VALUES (%s, 'sms', %s)",
            (case_id, assignee_account_id),
        )


def _rate(driver, *, profile="internal_copilot", user_id=None, **params):
    return execute_tool(
        tool="toee_feedback",
        action="submit_draft_rating",
        params=params,
        context=ToolExecutionContext(profile=profile, user_id=user_id),
        driver=driver,
    )


def _rating_count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM draft_feedback")
        return cur.fetchone()[0]


def _rating_audit_count(conn, *, action: str = "draft_rating_submitted") -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM workbench_audit_log WHERE action = %s", (action,)
        )
        return cur.fetchone()[0]


# --- happy path: real rows, read back directly from Postgres ------------------


def test_submit_draft_rating_up_persists_a_rated_only_row(datastore) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")

    result = _rate(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="up",
        draft_text="Hey, your tire order is on the way!",
    )
    assert result.ok
    rating_id = result.data["id"]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT case_id, draft_correlation_id, draft_kind, draft_text, "
            "outcome, verdict, reason_tags, rep_account_id, created_at "
            "FROM draft_feedback WHERE id = %s",
            (rating_id,),
        )
        row = cur.fetchone()
    assert row is not None
    (
        case_id,
        corr_id,
        draft_kind,
        draft_text,
        outcome,
        verdict,
        reason_tags,
        rep,
        created_at,
    ) = row
    assert case_id == "case_1"
    assert corr_id == "draft_corr_1"
    assert draft_kind == "sms"
    # S06 review (Important): the generated-draft snapshot persists and reads
    # back verbatim from live Postgres -- a rated_only row has no linked
    # outcome row to recover this from otherwise.
    assert draft_text == "Hey, your tire order is on the way!"
    assert outcome == "rated_only"
    assert verdict == "up"
    assert reason_tags == []
    assert rep == "acct_rep_1"
    assert created_at is not None


def test_submit_draft_rating_missing_draft_text_persists_nothing(datastore) -> None:
    # S06 review (Important): draft_text is now REQUIRED -- a rated_only row
    # has no linked outcome row (record_draft_outcome only fires on a send),
    # so without this the generated draft a down-rating refers to is lost.
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")

    result = _rate(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="up",
    )
    assert not result.ok
    assert result.error_class == "unexpected_error"
    assert _rating_count(conn) == 0
    assert _rating_audit_count(conn) == 0


def test_submit_draft_rating_down_with_tags_persists(datastore) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")

    result = _rate(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_2",
        draft_kind="email",
        verdict="down",
        reason_tags=["wrong_tone", "too_verbose"],
        comment="Rewrote the whole thing.",
        draft_text="Original generated draft body.",
    )
    assert result.ok

    with conn.cursor() as cur:
        cur.execute(
            "SELECT verdict, reason_tags, comment FROM draft_feedback WHERE id = %s",
            (result.data["id"],),
        )
        verdict, reason_tags, comment = cur.fetchone()
    assert verdict == "down"
    assert set(reason_tags) == {"wrong_tone", "too_verbose"}
    assert comment == "Rewrote the whole thing."


def test_submit_draft_rating_writes_an_audit_row(datastore) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")

    result = _rate(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="up",
        draft_text="Hey, your tire order is on the way!",
    )
    assert result.ok

    with conn.cursor() as cur:
        cur.execute(
            "SELECT account_id, action, target_type, target_id "
            "FROM workbench_audit_log WHERE action = 'draft_rating_submitted'"
        )
        row = cur.fetchone()
    assert row is not None
    account_id, action, target_type, target_id = row
    assert account_id == "acct_rep_1"
    assert action == "draft_rating_submitted"
    assert target_type == "case"
    assert target_id == "case_1"


# --- append-only: two ratings on one draft -> two rows -------------------------


def test_submit_draft_rating_is_append_only(datastore) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")

    first = _rate(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="up",
        draft_text="Hey, your tire order is on the way!",
    )
    second = _rate(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="down",
        reason_tags=["wrong_tone"],
        draft_text="Hey, your tire order is on the way!",
    )
    assert first.ok and second.ok
    assert first.data["id"] != second.data["id"]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM draft_feedback WHERE draft_correlation_id = %s",
            ("draft_corr_1",),
        )
        assert cur.fetchone()[0] == 2


# --- THE governance test: no actor -> zero rows, zero audit rows --------------


def test_submit_draft_rating_with_no_actor_persists_nothing(datastore) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")

    result = _rate(
        driver,
        user_id=None,
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="up",
    )
    assert not result.ok
    assert result.error_class == "policy_blocked"
    assert _rating_count(conn) == 0
    assert _rating_audit_count(conn) == 0


def test_submit_draft_rating_is_policy_blocked_outside_internal_copilot(
    datastore,
) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")

    result = _rate(
        driver,
        profile="customer_service_external",
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="up",
    )
    assert not result.ok
    assert result.error_class == "policy_blocked"
    assert _rating_count(conn) == 0


# --- THE case-ownership test: rate a case you don't hold -> zero rows --------


def test_submit_draft_rating_on_a_case_the_actor_does_not_hold_persists_nothing(
    datastore,
) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_other_rep")

    result = _rate(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="up",
        draft_text="Hey, your tire order is on the way!",
    )
    assert not result.ok
    assert result.error_class == "policy_blocked"
    assert _rating_count(conn) == 0
    assert _rating_audit_count(conn) == 0


def test_submit_draft_rating_on_an_unassigned_case_persists_nothing(datastore) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id=None)

    result = _rate(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="up",
        draft_text="Hey, your tire order is on the way!",
    )
    assert not result.ok
    assert result.error_class == "policy_blocked"
    assert _rating_count(conn) == 0


def test_submit_draft_rating_on_a_nonexistent_case_persists_nothing(datastore) -> None:
    driver, conn, _ = datastore

    result = _rate(
        driver,
        user_id="acct_rep_1",
        case_id="case_does_not_exist",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="up",
        draft_text="Hey, your tire order is on the way!",
    )
    assert not result.ok
    assert result.error_class == "policy_blocked"
    assert _rating_count(conn) == 0


# --- DB-level CHECK: the floor holds even if a handler bug skips validation ---


def test_db_check_rejects_down_with_empty_tags_even_via_raw_sql(datastore) -> None:
    # Proves the CONSTRAINT itself, independent of the handler -- same
    # coalesce()-matters reasoning as interaction_review's equivalent test
    # above, verified here for draft_feedback's own CHECK.
    _, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")
    with conn.cursor() as cur:
        with pytest.raises(Exception):
            cur.execute(
                "INSERT INTO draft_feedback "
                "(id, case_id, draft_correlation_id, draft_kind, outcome, "
                "verdict, reason_tags, rep_account_id) "
                "VALUES ('draft_raw', 'case_1', 'corr_raw', 'sms', 'rated_only', "
                "'down', '{}', 'acct_rep_1')"
            )
    conn.rollback()


# --- rejections persist nothing ------------------------------------------------


def test_submit_draft_rating_down_without_tags_persists_nothing(datastore) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")

    result = _rate(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="down",
    )
    assert not result.ok
    assert result.error_class == "unexpected_error"
    assert _rating_count(conn) == 0


def test_submit_draft_rating_rejects_external_tag_and_persists_nothing(
    datastore,
) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")

    result = _rate(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="down",
        reason_tags=["tool_misuse"],  # external (interaction-review) set
    )
    assert not result.ok
    assert result.error_class == "unexpected_error"
    assert _rating_count(conn) == 0


def test_submit_draft_rating_rejects_unknown_draft_kind_and_persists_nothing(
    datastore,
) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")

    result = _rate(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="call",
        verdict="up",
    )
    assert not result.ok
    assert result.error_class == "unexpected_error"
    assert _rating_count(conn) == 0


# --- model-supplied actor/verdict cannot be forged -----------------------------


def test_submit_draft_rating_rep_cannot_be_forged(datastore) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_real")

    result = _rate(
        driver,
        user_id="acct_real",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="up",
        rep_account_id="acct_forged",
        draft_text="Hey, your tire order is on the way!",
    )
    assert result.ok
    assert result.data["rep_account_id"] == "acct_real"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT rep_account_id FROM draft_feedback WHERE id = %s",
            (result.data["id"],),
        )
        assert cur.fetchone()[0] == "acct_real"


# --- record_draft_outcome (S08): the IMPLICIT mechanism ------------------------


def _record(driver, *, profile="internal_copilot", user_id=None, **params):
    return execute_tool(
        tool="toee_feedback",
        action="record_draft_outcome",
        params=params,
        context=ToolExecutionContext(profile=profile, user_id=user_id),
        driver=driver,
    )


def _outcome_audit_count(conn, *, action: str = "draft_outcome_recorded") -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM workbench_audit_log WHERE action = %s", (action,)
        )
        return cur.fetchone()[0]


def test_record_draft_outcome_sent_as_is_persists_a_row(datastore) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")

    result = _record(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        outcome="sent_as_is",
        draft_text="Hey, your tire order is on the way!",
    )
    assert result.ok
    outcome_id = result.data["id"]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT case_id, draft_correlation_id, draft_kind, draft_text, "
            "outcome, edit_distance_ratio, verdict, reason_tags, "
            "rep_account_id, created_at FROM draft_feedback WHERE id = %s",
            (outcome_id,),
        )
        row = cur.fetchone()
    assert row is not None
    (
        case_id,
        corr_id,
        draft_kind,
        draft_text,
        outcome,
        ratio,
        verdict,
        reason_tags,
        rep,
        created_at,
    ) = row
    assert case_id == "case_1"
    assert corr_id == "draft_corr_1"
    assert draft_kind == "sms"
    assert draft_text == "Hey, your tire order is on the way!"
    assert outcome == "sent_as_is"
    assert ratio is None
    assert verdict is None
    assert reason_tags == []
    assert rep == "acct_rep_1"
    assert created_at is not None


def test_record_draft_outcome_sent_edited_persists_a_plausible_ratio(datastore) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")

    result = _record(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_2",
        draft_kind="email",
        outcome="sent_edited",
        edit_distance_ratio=0.42,
        draft_text="Original generated draft body.",
    )
    assert result.ok
    outcome_id = result.data["id"]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT outcome, edit_distance_ratio FROM draft_feedback WHERE id = %s",
            (outcome_id,),
        )
        outcome, ratio = cur.fetchone()
    assert outcome == "sent_edited"
    assert ratio == pytest.approx(0.42)


def test_record_draft_outcome_writes_an_audit_row(datastore) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")

    result = _record(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        outcome="sent_as_is",
        draft_text="Hey, your tire order is on the way!",
    )
    assert result.ok

    with conn.cursor() as cur:
        cur.execute(
            "SELECT account_id, action, target_type, target_id "
            "FROM workbench_audit_log WHERE action = 'draft_outcome_recorded'"
        )
        row = cur.fetchone()
    assert row is not None
    account_id, action, target_type, target_id = row
    assert account_id == "acct_rep_1"
    assert action == "draft_outcome_recorded"
    assert target_type == "case"
    assert target_id == "case_1"


# --- THE correlation-join test: a rating and an outcome for the SAME draft ----


def test_rating_and_outcome_for_the_same_draft_share_correlation_id_as_two_rows(
    datastore,
) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")

    rating = _rate(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_join",
        draft_kind="sms",
        verdict="up",
        draft_text="Hey, your tire order is on the way!",
    )
    outcome = _record(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_join",
        draft_kind="sms",
        outcome="sent_as_is",
        draft_text="Hey, your tire order is on the way!",
    )
    assert rating.ok and outcome.ok
    assert rating.data["id"] != outcome.data["id"]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, outcome, verdict FROM draft_feedback "
            "WHERE draft_correlation_id = %s ORDER BY created_at",
            ("draft_corr_join",),
        )
        rows = cur.fetchall()
    assert len(rows) == 2
    ids = {row[0] for row in rows}
    assert ids == {rating.data["id"], outcome.data["id"]}
    outcomes_by_id = {row[0]: (row[1], row[2]) for row in rows}
    assert outcomes_by_id[rating.data["id"]] == ("rated_only", "up")
    assert outcomes_by_id[outcome.data["id"]] == ("sent_as_is", None)


# --- THE governance test: no actor -> zero rows, zero audit rows --------------


def test_record_draft_outcome_with_no_actor_persists_nothing(datastore) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")

    result = _record(
        driver,
        user_id=None,
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        outcome="sent_as_is",
        draft_text="Hey, your tire order is on the way!",
    )
    assert not result.ok
    assert result.error_class == "policy_blocked"
    assert _rating_count(conn) == 0
    assert _outcome_audit_count(conn) == 0


def test_record_draft_outcome_is_policy_blocked_outside_internal_copilot(
    datastore,
) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")

    result = _record(
        driver,
        profile="customer_service_external",
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        outcome="sent_as_is",
        draft_text="Hey, your tire order is on the way!",
    )
    assert not result.ok
    assert result.error_class == "policy_blocked"
    assert _rating_count(conn) == 0


# --- THE case-ownership test: record an outcome on a case you don't hold -----


def test_record_draft_outcome_on_a_case_the_actor_does_not_hold_persists_nothing(
    datastore,
) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_other_rep")

    result = _record(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        outcome="sent_as_is",
        draft_text="Hey, your tire order is on the way!",
    )
    assert not result.ok
    assert result.error_class == "policy_blocked"
    assert _rating_count(conn) == 0
    assert _outcome_audit_count(conn) == 0


def test_record_draft_outcome_on_a_nonexistent_case_persists_nothing(datastore) -> None:
    driver, conn, _ = datastore

    result = _record(
        driver,
        user_id="acct_rep_1",
        case_id="case_does_not_exist",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        outcome="sent_as_is",
        draft_text="Hey, your tire order is on the way!",
    )
    assert not result.ok
    assert result.error_class == "policy_blocked"
    assert _rating_count(conn) == 0


# --- rejections persist nothing ------------------------------------------------


def test_record_draft_outcome_sent_edited_without_ratio_persists_nothing(
    datastore,
) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")

    result = _record(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        outcome="sent_edited",
        draft_text="Hey, your tire order is on the way!",
    )
    assert not result.ok
    assert result.error_class == "unexpected_error"
    assert _rating_count(conn) == 0


def test_record_draft_outcome_sent_as_is_with_ratio_persists_nothing(
    datastore,
) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")

    result = _record(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        outcome="sent_as_is",
        edit_distance_ratio=0.1,
        draft_text="Hey, your tire order is on the way!",
    )
    assert not result.ok
    assert result.error_class == "unexpected_error"
    assert _rating_count(conn) == 0


def test_record_draft_outcome_rejects_unknown_outcome_and_persists_nothing(
    datastore,
) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")

    result = _record(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        outcome="ignored",
        draft_text="Hey, your tire order is on the way!",
    )
    assert not result.ok
    assert result.error_class == "unexpected_error"
    assert _rating_count(conn) == 0


def test_record_draft_outcome_missing_draft_text_persists_nothing(datastore) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_rep_1")

    result = _record(
        driver,
        user_id="acct_rep_1",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        outcome="sent_as_is",
    )
    assert not result.ok
    assert result.error_class == "unexpected_error"
    assert _rating_count(conn) == 0


# --- model-supplied actor cannot be forged -------------------------------------


def test_record_draft_outcome_rep_cannot_be_forged(datastore) -> None:
    driver, conn, _ = datastore
    _insert_case(conn, case_id="case_1", assignee_account_id="acct_real")

    result = _record(
        driver,
        user_id="acct_real",
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        outcome="sent_as_is",
        draft_text="Hey, your tire order is on the way!",
        rep_account_id="acct_forged",
    )
    assert result.ok
    assert result.data["rep_account_id"] == "acct_real"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT rep_account_id FROM draft_feedback WHERE id = %s",
            (result.data["id"],),
        )
        assert cur.fetchone()[0] == "acct_real"
