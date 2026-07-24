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
