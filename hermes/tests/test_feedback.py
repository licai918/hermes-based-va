"""Mock handlers for ``toee_feedback`` (0.0.4 S03, ADR-0154, FR-1/2/4/NFR-2/5).

``submit_interaction_review`` is the EXTERNAL mechanism's write path: a
supervisor's pass/fail judgment on one Auto-Handled Interaction record or one
sales_outreach Follow-up Case. This exercises the STORE + governed WRITE tool
+ validation + the fail-closed authorization gate over the mock twin --
mirrors ``test_agent_experience.py``'s shape for ``propose_experience``.
"""

from __future__ import annotations

from toee_hermes.drivers.mock.driver import MockDriver
from toee_hermes.drivers.mock.feedback import create_feedback_mock_handlers
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext


def _driver() -> MockDriver:
    return MockDriver(create_feedback_mock_handlers())


def _internal_ctx(user_id: str | None = None) -> ToolExecutionContext:
    return ToolExecutionContext(profile="internal_copilot", user_id=user_id)


def _external_ctx() -> ToolExecutionContext:
    return ToolExecutionContext(profile="customer_service_external")


def _submit(driver, context, **params):
    return execute_tool(
        tool="toee_feedback",
        action="submit_interaction_review",
        params=params,
        context=context,
        driver=driver,
    )


# --- happy path ---------------------------------------------------------------


def test_submit_interaction_review_pass_needs_no_tags() -> None:
    driver = _driver()
    result = _submit(
        driver,
        _internal_ctx(user_id="acct_super_1"),
        subject_kind="auto_handled_record",
        subject_id="rec_1",
        verdict="pass",
    )

    assert result.ok is True
    assert result.data["subject_kind"] == "auto_handled_record"
    assert result.data["subject_id"] == "rec_1"
    assert result.data["verdict"] == "pass"
    assert result.data["reason_tags"] == []
    # RK-1 parity: reviewer is framework-derived, never a model-supplied param.
    assert result.data["reviewer_account_id"] == "acct_super_1"


def test_submit_interaction_review_fail_with_tags_and_comment() -> None:
    driver = _driver()
    result = _submit(
        driver,
        _internal_ctx(user_id="acct_super_1"),
        subject_kind="sales_outreach_case",
        subject_id="case_9",
        verdict="fail",
        reason_tags=["factual_error", "tool_misuse"],
        comment="Quoted the wrong SKU.",
    )

    assert result.ok is True
    assert result.data["verdict"] == "fail"
    assert result.data["reason_tags"] == ["factual_error", "tool_misuse"]
    assert result.data["comment"] == "Quoted the wrong SKU."


# --- validation: rejections persist nothing ------------------------------------


def test_submit_interaction_review_rejects_unknown_subject_kind() -> None:
    driver = _driver()
    result = _submit(
        driver,
        _internal_ctx(user_id="acct_super_1"),
        subject_kind="conversation_thread",
        subject_id="thread_1",
        verdict="pass",
    )
    assert result.ok is False
    assert result.error_class == "unexpected_error"


def test_submit_interaction_review_rejects_unknown_verdict() -> None:
    driver = _driver()
    result = _submit(
        driver,
        _internal_ctx(user_id="acct_super_1"),
        subject_kind="auto_handled_record",
        subject_id="rec_1",
        verdict="maybe",
    )
    assert result.ok is False
    assert result.error_class == "unexpected_error"


def test_submit_interaction_review_fail_without_tags_is_rejected() -> None:
    driver = _driver()
    result = _submit(
        driver,
        _internal_ctx(user_id="acct_super_1"),
        subject_kind="auto_handled_record",
        subject_id="rec_1",
        verdict="fail",
    )
    assert result.ok is False
    assert result.error_class == "unexpected_error"


def test_submit_interaction_review_rejects_a_tag_from_the_internal_set() -> None:
    # ADR-0154: the internal (draft-rating) tag set is deliberately separate --
    # "wrong_tone" belongs to submit_draft_rating, not here.
    driver = _driver()
    result = _submit(
        driver,
        _internal_ctx(user_id="acct_super_1"),
        subject_kind="auto_handled_record",
        subject_id="rec_1",
        verdict="fail",
        reason_tags=["wrong_tone"],
    )
    assert result.ok is False
    assert result.error_class == "unexpected_error"


# --- fail-closed authorization: the governance non-negotiable -----------------


def test_submit_interaction_review_with_no_actor_is_policy_blocked() -> None:
    driver = _driver()
    result = _submit(
        driver,
        _internal_ctx(user_id=None),
        subject_kind="auto_handled_record",
        subject_id="rec_1",
        verdict="pass",
    )
    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_submit_interaction_review_is_policy_blocked_outside_internal_copilot() -> None:
    # Defense in depth: toee_feedback is not allowlisted for EXTERNAL
    # (ADR-0034/35), so this is unreachable in production, but the resolver
    # itself must still fail closed.
    driver = _driver()
    result = _submit(
        driver,
        _external_ctx(),
        subject_kind="auto_handled_record",
        subject_id="rec_1",
        verdict="pass",
    )
    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_submit_interaction_review_reviewer_cannot_be_forged() -> None:
    # A model-supplied reviewer_account_id/actor param is ignored -- the
    # framework-derived context.user_id always wins (RK-1 parity with
    # resolve_agent_experience_source's forged-"source" test).
    driver = _driver()
    result = _submit(
        driver,
        _internal_ctx(user_id="acct_real"),
        subject_kind="auto_handled_record",
        subject_id="rec_1",
        verdict="pass",
        reviewer_account_id="acct_forged",
    )
    assert result.ok is True
    assert result.data["reviewer_account_id"] == "acct_real"


# --- append-only: two reviews by one reviewer yield two rows -------------------


def test_submit_interaction_review_is_append_only() -> None:
    driver = _driver()
    ctx = _internal_ctx(user_id="acct_super_1")
    first = _submit(
        driver, ctx, subject_kind="auto_handled_record", subject_id="rec_1", verdict="pass"
    )
    second = _submit(
        driver,
        ctx,
        subject_kind="auto_handled_record",
        subject_id="rec_1",
        verdict="fail",
        reason_tags=["tone_inappropriate"],
    )
    assert first.ok is True and second.ok is True
    assert first.data["id"] != second.data["id"]


# --- submit_draft_rating (S06): the INTERNAL mechanism -------------------------


def _rate(driver, context, **params):
    return execute_tool(
        tool="toee_feedback",
        action="submit_draft_rating",
        params=params,
        context=context,
        driver=driver,
    )


def test_submit_draft_rating_up_needs_no_tags() -> None:
    driver = _driver()
    result = _rate(
        driver,
        _internal_ctx(user_id="acct_rep_1"),
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="up",
        draft_text="Hey, your tire order is on the way!",
    )

    assert result.ok is True
    assert result.data["case_id"] == "case_1"
    assert result.data["draft_kind"] == "sms"
    assert result.data["verdict"] == "up"
    assert result.data["reason_tags"] == []
    assert result.data["outcome"] == "rated_only"
    # S06 review (Important): the generated-draft snapshot is captured too --
    # a rated_only row has no linked outcome row to recover it from otherwise.
    assert result.data["draft_text"] == "Hey, your tire order is on the way!"
    # RK-1 parity: the rep is framework-derived, never a model-supplied param.
    assert result.data["rep_account_id"] == "acct_rep_1"


def test_submit_draft_rating_missing_draft_text_is_rejected() -> None:
    # S06 review (Important): draft_text is now REQUIRED -- without it, a
    # down-rating's generated draft would be unrecoverable (no linked outcome
    # row exists for a rated_only row).
    driver = _driver()
    result = _rate(
        driver,
        _internal_ctx(user_id="acct_rep_1"),
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="up",
    )
    assert result.ok is False
    assert result.error_class == "unexpected_error"


def test_submit_draft_rating_down_with_tags_and_comment() -> None:
    driver = _driver()
    result = _rate(
        driver,
        _internal_ctx(user_id="acct_rep_1"),
        case_id="case_1",
        draft_correlation_id="draft_corr_2",
        draft_kind="email",
        verdict="down",
        reason_tags=["wrong_tone", "too_verbose"],
        comment="Rewrote the whole thing.",
        draft_text="Original generated draft body.",
    )

    assert result.ok is True
    assert result.data["verdict"] == "down"
    assert result.data["reason_tags"] == ["wrong_tone", "too_verbose"]
    assert result.data["comment"] == "Rewrote the whole thing."


def test_submit_draft_rating_rejects_unknown_draft_kind() -> None:
    driver = _driver()
    result = _rate(
        driver,
        _internal_ctx(user_id="acct_rep_1"),
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="call",
        verdict="up",
    )
    assert result.ok is False
    assert result.error_class == "unexpected_error"


def test_submit_draft_rating_down_without_tags_is_rejected() -> None:
    driver = _driver()
    result = _rate(
        driver,
        _internal_ctx(user_id="acct_rep_1"),
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="down",
    )
    assert result.ok is False
    assert result.error_class == "unexpected_error"


def test_submit_draft_rating_rejects_a_tag_from_the_external_set() -> None:
    # ADR-0154: the external (interaction-review) tag set is deliberately
    # separate -- "factual_error" is shared, but "tool_misuse" belongs to
    # submit_interaction_review, not here.
    driver = _driver()
    result = _rate(
        driver,
        _internal_ctx(user_id="acct_rep_1"),
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="down",
        reason_tags=["tool_misuse"],
    )
    assert result.ok is False
    assert result.error_class == "unexpected_error"


def test_submit_draft_rating_with_no_actor_is_policy_blocked() -> None:
    driver = _driver()
    result = _rate(
        driver,
        _internal_ctx(user_id=None),
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="up",
    )
    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_submit_draft_rating_is_policy_blocked_outside_internal_copilot() -> None:
    driver = _driver()
    result = _rate(
        driver,
        _external_ctx(),
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="up",
    )
    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_submit_draft_rating_rep_cannot_be_forged() -> None:
    driver = _driver()
    result = _rate(
        driver,
        _internal_ctx(user_id="acct_real"),
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="up",
        rep_account_id="acct_forged",
        draft_text="Hey, your tire order is on the way!",
    )
    assert result.ok is True
    assert result.data["rep_account_id"] == "acct_real"


def test_submit_draft_rating_is_append_only() -> None:
    driver = _driver()
    ctx = _internal_ctx(user_id="acct_rep_1")
    first = _rate(
        driver,
        ctx,
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="up",
        draft_text="Hey, your tire order is on the way!",
    )
    second = _rate(
        driver,
        ctx,
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        verdict="down",
        reason_tags=["wrong_tone"],
        draft_text="Hey, your tire order is on the way!",
    )
    assert first.ok is True and second.ok is True
    assert first.data["id"] != second.data["id"]


# --- record_draft_outcome (S08): the IMPLICIT mechanism ------------------------


def _record(driver, context, **params):
    return execute_tool(
        tool="toee_feedback",
        action="record_draft_outcome",
        params=params,
        context=context,
        driver=driver,
    )


def test_record_draft_outcome_sent_as_is() -> None:
    driver = _driver()
    result = _record(
        driver,
        _internal_ctx(user_id="acct_rep_1"),
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        outcome="sent_as_is",
        draft_text="Hey, your tire order is on the way!",
    )

    assert result.ok is True
    assert result.data["outcome"] == "sent_as_is"
    assert result.data["edit_distance_ratio"] is None
    assert result.data["verdict"] is None
    assert result.data["reason_tags"] == []
    # RK-1 parity: the rep is framework-derived, never a model-supplied param.
    assert result.data["rep_account_id"] == "acct_rep_1"


def test_record_draft_outcome_sent_edited_with_ratio() -> None:
    driver = _driver()
    result = _record(
        driver,
        _internal_ctx(user_id="acct_rep_1"),
        case_id="case_1",
        draft_correlation_id="draft_corr_2",
        draft_kind="email",
        outcome="sent_edited",
        edit_distance_ratio=0.35,
        draft_text="Original generated draft body.",
    )

    assert result.ok is True
    assert result.data["outcome"] == "sent_edited"
    assert result.data["edit_distance_ratio"] == 0.35


def test_record_draft_outcome_sent_edited_requires_ratio() -> None:
    driver = _driver()
    result = _record(
        driver,
        _internal_ctx(user_id="acct_rep_1"),
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        outcome="sent_edited",
        draft_text="Hey, your tire order is on the way!",
    )
    assert result.ok is False
    assert result.error_class == "unexpected_error"


def test_record_draft_outcome_sent_as_is_rejects_ratio() -> None:
    driver = _driver()
    result = _record(
        driver,
        _internal_ctx(user_id="acct_rep_1"),
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        outcome="sent_as_is",
        edit_distance_ratio=0.2,
        draft_text="Hey, your tire order is on the way!",
    )
    assert result.ok is False
    assert result.error_class == "unexpected_error"


def test_record_draft_outcome_rejects_unknown_outcome() -> None:
    driver = _driver()
    result = _record(
        driver,
        _internal_ctx(user_id="acct_rep_1"),
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        outcome="ignored",
        draft_text="Hey, your tire order is on the way!",
    )
    assert result.ok is False
    assert result.error_class == "unexpected_error"


def test_record_draft_outcome_missing_draft_text_is_rejected() -> None:
    driver = _driver()
    result = _record(
        driver,
        _internal_ctx(user_id="acct_rep_1"),
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        outcome="sent_as_is",
    )
    assert result.ok is False
    assert result.error_class == "unexpected_error"


def test_record_draft_outcome_with_no_actor_is_policy_blocked() -> None:
    driver = _driver()
    result = _record(
        driver,
        _internal_ctx(user_id=None),
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        outcome="sent_as_is",
        draft_text="Hey, your tire order is on the way!",
    )
    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_record_draft_outcome_is_policy_blocked_outside_internal_copilot() -> None:
    driver = _driver()
    result = _record(
        driver,
        _external_ctx(),
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        outcome="sent_as_is",
        draft_text="Hey, your tire order is on the way!",
    )
    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_record_draft_outcome_rep_cannot_be_forged() -> None:
    driver = _driver()
    result = _record(
        driver,
        _internal_ctx(user_id="acct_real"),
        case_id="case_1",
        draft_correlation_id="draft_corr_1",
        draft_kind="sms",
        outcome="sent_as_is",
        draft_text="Hey, your tire order is on the way!",
        rep_account_id="acct_forged",
    )
    assert result.ok is True
    assert result.data["rep_account_id"] == "acct_real"


def test_record_draft_outcome_and_submit_draft_rating_share_correlation_id() -> None:
    # S08 brief: rows written by record_draft_outcome and submit_draft_rating
    # for the SAME draft share the draft_correlation_id -- one draft's
    # implicit + explicit signals join.
    driver = _driver()
    ctx = _internal_ctx(user_id="acct_rep_1")
    rating = _rate(
        driver,
        ctx,
        case_id="case_1",
        draft_correlation_id="draft_corr_join",
        draft_kind="sms",
        verdict="up",
        draft_text="Hey, your tire order is on the way!",
    )
    outcome = _record(
        driver,
        ctx,
        case_id="case_1",
        draft_correlation_id="draft_corr_join",
        draft_kind="sms",
        outcome="sent_as_is",
        draft_text="Hey, your tire order is on the way!",
    )
    assert rating.ok is True and outcome.ok is True
    assert rating.data["id"] != outcome.data["id"]
    assert (
        rating.data["draft_correlation_id"]
        == outcome.data["draft_correlation_id"]
        == "draft_corr_join"
    )
