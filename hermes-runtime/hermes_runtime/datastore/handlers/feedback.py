"""Postgres handler for ``toee_feedback`` (0.0.4 S03/S06, ADR-0154, FR-1/2/4/NFR-2/5).

``submit_interaction_review`` is the EXTERNAL mechanism's write: a supervisor's
pass/fail judgment on one Auto-Handled Interaction record or one
sales_outreach Follow-up Case. ``submit_draft_rating`` (S06) is the INTERNAL
mechanism's write: a rep's thumbs-up/down on one Copilot Draft Action draft,
PLUS a case-ownership gate (the acting rep must hold the case -- mirrors
``_send_sms_message``'s assignee check in ``datastore/handlers/cases.py``).
Both mirror the ``agent_experience`` Postgres handler's shape (validate,
INSERT + ``insert_audit`` in the SAME transaction, return a dict) and reuse
the SAME validation/authorization helpers the mock twin uses (imported from
``toee_hermes.drivers.mock.feedback`` -- the "one resolver, both twins"
discipline) so the two backends can't silently drift on what a governed
rejection is. ``record_draft_outcome`` (S08) and the real ``list_feedback``
read (S10) are not registered yet -- this fragment only carries what S03/S06
ship.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg.rows import dict_row

from toee_hermes.drivers.mock.feedback import (
    _read_comment,
    _read_draft_text,
    _read_internal_reason_tags,
    _read_rating_comment,
    _read_reason_tags,
    _require_case_id,
    _require_draft_correlation_id,
    _require_draft_kind,
    _require_draft_rating_verdict,
    _require_subject_id,
    _require_subject_kind,
    _require_verdict,
    resolve_draft_rating_authorization,
    resolve_interaction_review_authorization,
)
from toee_hermes.errors import ToolDriverError

from ._common import insert_audit, new_id, serialize_row

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext

_REVIEW_COLUMNS = (
    "id, subject_kind, subject_id, verdict, reason_tags, comment, "
    "reviewer_account_id, created_at"
)


def _submit_interaction_review(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    # The gate runs FIRST: a missing/unauthorized actor is ALWAYS policy_blocked
    # regardless of how malformed the rest of the payload is, and NOTHING below
    # this line runs (and thus nothing is ever built to INSERT) when it raises --
    # this is the "AI cannot score itself" guarantee, structural not a prompt rule.
    reviewer_account_id = resolve_interaction_review_authorization(context)
    subject_kind = _require_subject_kind(params)
    subject_id = _require_subject_id(params)
    verdict = _require_verdict(params)
    reason_tags = _read_reason_tags(params, verdict=verdict)
    comment = _read_comment(params)

    review_id = new_id("irev")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            INSERT INTO interaction_review
                (id, subject_kind, subject_id, verdict, reason_tags, comment,
                 reviewer_account_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING {_REVIEW_COLUMNS}
            """,
            (
                review_id,
                subject_kind,
                subject_id,
                verdict,
                reason_tags,
                comment,
                reviewer_account_id,
            ),
        )
        row = cur.fetchone()
    insert_audit(
        conn,
        profile=context.profile,
        account_id=reviewer_account_id,
        action="interaction_review_submitted",
        target_type=subject_kind,
        target_id=subject_id,
        details={"verdict": verdict, "reason_tags": reason_tags},
    )
    return serialize_row(row)


_DRAFT_RATING_COLUMNS = (
    "id, case_id, draft_correlation_id, draft_kind, draft_text, outcome, "
    "edit_distance_ratio, verdict, reason_tags, comment, rep_account_id, "
    "created_at"
)


def _require_case_held_by(conn, *, case_id: str, actor: str) -> None:
    """Case-ownership gate for submit_draft_rating (S06 brief).

    Mirrors ``_send_sms_message``'s assignee check (``datastore/handlers/
    cases.py``): a missing case or one assigned to someone else is
    ``policy_blocked``, same error class as the missing-actor gate, so a
    caller can't distinguish "no case" from "not your case" and probe for
    case existence.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT assignee_account_id FROM cases WHERE id = %s", (case_id,))
        row = cur.fetchone()
    if row is None or row[0] != actor:
        raise ToolDriverError(
            "policy_blocked", "case not held by the acting rep; rating refused."
        )


def _submit_draft_rating(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    # The gate runs FIRST, same discipline as _submit_interaction_review: a
    # missing/unauthorized actor is ALWAYS policy_blocked before anything else
    # in the payload is read, let alone hits the database.
    rep_account_id = resolve_draft_rating_authorization(context)
    case_id = _require_case_id(params)
    draft_correlation_id = _require_draft_correlation_id(params)
    draft_kind = _require_draft_kind(params)
    verdict = _require_draft_rating_verdict(params)
    reason_tags = _read_internal_reason_tags(params, verdict=verdict)
    comment = _read_rating_comment(params)
    draft_text = _read_draft_text(params)

    # Additional gate for THIS mechanism only (S06 brief): the acting rep must
    # hold the case the draft belongs to.
    _require_case_held_by(conn, case_id=case_id, actor=rep_account_id)

    rating_id = new_id("draft")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            INSERT INTO draft_feedback
                (id, case_id, draft_correlation_id, draft_kind, draft_text,
                 outcome, verdict, reason_tags, comment, rep_account_id)
            VALUES (%s, %s, %s, %s, %s, 'rated_only', %s, %s, %s, %s)
            RETURNING {_DRAFT_RATING_COLUMNS}
            """,
            (
                rating_id,
                case_id,
                draft_correlation_id,
                draft_kind,
                draft_text,
                verdict,
                reason_tags,
                comment,
                rep_account_id,
            ),
        )
        row = cur.fetchone()
    insert_audit(
        conn,
        profile=context.profile,
        account_id=rep_account_id,
        action="draft_rating_submitted",
        target_type="case",
        target_id=case_id,
        details={"verdict": verdict, "reason_tags": reason_tags},
    )
    return serialize_row(row)


def feedback_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for ``toee_feedback`` (grows with S08/S10)."""
    return {
        "toee_feedback": {
            "submit_interaction_review": _submit_interaction_review,
            "submit_draft_rating": _submit_draft_rating,
        }
    }
