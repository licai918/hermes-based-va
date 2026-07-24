"""Postgres handler for ``toee_feedback`` (0.0.4 S03, ADR-0154, FR-1/2/4/NFR-2/5).

``submit_interaction_review`` is the EXTERNAL mechanism's write: a supervisor's
pass/fail judgment on one Auto-Handled Interaction record or one
sales_outreach Follow-up Case. Mirrors the ``agent_experience`` Postgres
handler's shape (validate, INSERT + ``insert_audit`` in the SAME transaction,
return a dict) and reuses the SAME validation/authorization helpers the mock
twin uses (``resolve_interaction_review_authorization`` etc., imported from
``toee_hermes.drivers.mock.feedback`` -- the "one resolver, both twins"
discipline) so the two backends can't silently drift on what a governed
rejection is. ``record_draft_outcome``/``submit_draft_rating`` (S06/S08) and
the real ``list_feedback`` read (S10) are not registered yet -- this fragment
only carries what S03 ships.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg.rows import dict_row

from toee_hermes.drivers.mock.feedback import (
    _read_comment,
    _read_reason_tags,
    _require_subject_id,
    _require_subject_kind,
    _require_verdict,
    resolve_interaction_review_authorization,
)

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


def feedback_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for ``toee_feedback`` (grows with S06/S08/S10)."""
    return {
        "toee_feedback": {
            "submit_interaction_review": _submit_interaction_review,
        }
    }
