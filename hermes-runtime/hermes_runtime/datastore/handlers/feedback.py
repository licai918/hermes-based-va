"""Postgres handler for ``toee_feedback`` (0.0.4 S03/S06, ADR-0154, FR-1/2/4/NFR-2/5).

``submit_interaction_review`` is the EXTERNAL mechanism's write: a supervisor's
pass/fail judgment on one Auto-Handled Interaction record or one
sales_outreach Follow-up Case, PLUS a role gate (FR-4: the acting account must
be a supervisor/admin, checked here via ``_require_supervisor_or_admin`` --
the mock twin has no ``workbench_account`` table to check a role against, see
the module docstring in ``toee_hermes.drivers.mock.feedback``). ``submit_
draft_rating`` (S06) is the INTERNAL mechanism's write: a rep's thumbs-up/down
on one Copilot Draft Action draft, PLUS a case-ownership gate (the acting rep
must hold the case -- mirrors ``_send_sms_message``'s assignee check in
``datastore/handlers/cases.py``). Both additional gates share the same shape:
DB-backed, Postgres-only, and ``policy_blocked`` without letting a caller
distinguish "no such account/case" from "wrong role/not yours".
``record_draft_outcome`` (S08) is the IMPLICIT counterpart to
``submit_draft_rating``: writes into the SAME ``draft_feedback`` table
whether the rep sent the generated draft untouched or edited it first,
reusing ``submit_draft_rating``'s actor resolver and case-ownership gate
verbatim (an outcome write is governed exactly like a rating write). All
three mirror the ``agent_experience`` Postgres handler's shape (validate,
INSERT + ``insert_audit`` in the SAME transaction, return a dict) and reuse
the SAME validation/authorization helpers the mock twin uses (imported from
``toee_hermes.drivers.mock.feedback`` -- the "one resolver, both twins"
discipline) so the two backends can't silently drift on what a governed
rejection is.

``list_feedback`` (S10, FR-3 read half) is the Supervisor Admin's governed
read over BOTH tables: bounded, filterable (``since``/``verdict``), and
read-only -- no actor, no audit row (mirrors ``list_agent_experience`` /
``dead_letter._list_dead_letters``). It is the seam Phase 2's aggregation
will consume.

**Known and accepted seam -- profile allowlisting is per TOOL, not per
ACTION** (record this so a future reader does not mistake the allowlist for
the actual boundary, per the S10 brief). ``toee_feedback`` is allowlisted on
BOTH ``internal_copilot`` (for the three writes above) and
``supervisor_admin`` (for ``list_feedback`` -- see ``toee_hermes.plugin.
profiles.PROFILE_TOOL_ALLOWLIST``). That means ``list_feedback`` is
dispatchable under the internal_copilot profile by the allowlist alone, same
as the three writes are by supervisor_admin -- the allowlist does not separate
them.

Two things do. ``_AGENT_EXCLUDED_ACTIONS`` (``toee_hermes.plugin``) holds all
four actions, so none ever reaches a live agent's own tool-calling loop on any
profile. And each action carries its OWN gate: the three writes fail closed
without a framework-resolved actor, and ``list_feedback`` --  which needs no
actor, being a read -- is gated on profile by
:func:`resolve_list_feedback_authorization`. Without that gate the copilot
profile could read every review, rating and reviewer comment; "no BFF route
maps to it yet" describes today's callers, not a boundary.

The per-profile ROUTE separation is a third layer still to come: a copilot BFF
route for the writes (S04/S07 built these) and the admin ``/admin`` surface for
``list_feedback`` (not built). A future reader should check the gates and the
routes -- never the allowlist -- to reason about who can reach an action.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg.rows import dict_row

from toee_hermes.drivers.mock.feedback import (
    _read_comment,
    _read_edit_distance_ratio,
    _read_internal_reason_tags,
    _read_list_limit,
    _read_rating_comment,
    _read_reason_tags,
    _read_since_filter,
    _read_verdict_filter,
    _require_case_id,
    _require_draft_correlation_id,
    _require_draft_kind,
    _require_draft_outcome,
    _require_draft_rating_verdict,
    _require_draft_text,
    _require_subject_id,
    _require_subject_kind,
    _require_verdict,
    resolve_draft_rating_authorization,
    resolve_interaction_review_authorization,
    resolve_list_feedback_authorization,
)
from toee_hermes.errors import ToolDriverError

from ._common import insert_audit, new_id, serialize_row

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext

_REVIEW_COLUMNS = (
    "id, subject_kind, subject_id, verdict, reason_tags, comment, "
    "reviewer_account_id, created_at"
)

# Workbench role ids allowed to submit an EXTERNAL interaction review (FR-4):
# supervisor or admin, never a rep. TS keeps the canonical set at
# packages/shared/src/profiles.ts::WORKBENCH_ROLES -- update both together so
# the two runtimes can't silently drift.
_REVIEWER_ROLES: tuple[str, ...] = ("workbench_supervisor", "workbench_admin")


def _require_supervisor_or_admin(conn, *, account_id: str) -> None:
    """FR-4 role gate for submit_interaction_review: supervisor/admin only.

    Runs AFTER ``resolve_interaction_review_authorization`` has already
    confirmed an attributed internal_copilot actor -- this is a SECOND,
    independent axis (who the actor *is*, not just that one was resolved).
    That lookup needs the real ``workbench_account`` table, so -- like
    ``_require_case_held_by`` below -- it lives ONLY in this Postgres
    handler; the mock has no account store to check a role against (see the
    module docstring in ``toee_hermes.drivers.mock.feedback``).

    Checks ``status`` as well as ``role``. ``disable_account`` sets status to
    'disabled' and login refuses a disabled account -- but a session issued
    BEFORE the disable stays valid until it expires, and nothing between here
    and the cookie re-checks the account. Without the status clause a
    just-revoked supervisor keeps writing judgments for the rest of that
    window, and they land in the audit trail looking entirely legitimate.
    (The broader gap -- that a live session is never revalidated against the
    account at all -- is app-wide and pre-existing, not this gate's to close.)

    Same "can't distinguish why" discipline as ``_require_case_held_by``: an
    unknown ``account_id``, a real rep account, and a disabled supervisor all
    fail closed to the identical ``policy_blocked`` message, so a caller can't
    use this gate's response to probe whether an account exists, what role it
    holds, or whether it is still active.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT role FROM workbench_account WHERE id = %s AND status = 'active'",
            (account_id,),
        )
        row = cur.fetchone()
    if row is None or row[0] not in _REVIEWER_ROLES:
        raise ToolDriverError(
            "policy_blocked",
            "interaction reviews require a supervisor or admin account.",
        )


def _submit_interaction_review(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    # The gate runs FIRST: a missing/unauthorized actor is ALWAYS policy_blocked
    # regardless of how malformed the rest of the payload is, and NOTHING below
    # this line runs (and thus nothing is ever built to INSERT) when it raises --
    # this is the "AI cannot score itself" guarantee, structural not a prompt rule.
    reviewer_account_id = resolve_interaction_review_authorization(context)
    # Second gate, same discipline, immediately after: WHO the actor is, not
    # just that one was resolved (FR-4). Still runs before any payload is even
    # read, so a rep's malformed submission and a rep's well-formed one fail
    # identically on role, never on payload validation.
    _require_supervisor_or_admin(conn, account_id=reviewer_account_id)
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
    draft_text = _require_draft_text(params)

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


def _record_draft_outcome(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    # Same gate-first ordering as _submit_draft_rating: a missing/unauthorized
    # actor is ALWAYS policy_blocked before anything else in the payload is
    # read. Reuses that resolver verbatim (S08 brief) -- an outcome write is
    # governed exactly like a rating write, just a different payload shape.
    rep_account_id = resolve_draft_rating_authorization(context)
    case_id = _require_case_id(params)
    draft_correlation_id = _require_draft_correlation_id(params)
    draft_kind = _require_draft_kind(params)
    outcome = _require_draft_outcome(params)
    draft_text = _require_draft_text(params)
    edit_distance_ratio = _read_edit_distance_ratio(params, outcome=outcome)

    # Same case-ownership gate as _submit_draft_rating (S06 brief): an outcome
    # is a governed write like any other.
    _require_case_held_by(conn, case_id=case_id, actor=rep_account_id)

    outcome_id = new_id("draft")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            INSERT INTO draft_feedback
                (id, case_id, draft_correlation_id, draft_kind, draft_text,
                 outcome, edit_distance_ratio, rep_account_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_DRAFT_RATING_COLUMNS}
            """,
            (
                outcome_id,
                case_id,
                draft_correlation_id,
                draft_kind,
                draft_text,
                outcome,
                edit_distance_ratio,
                rep_account_id,
            ),
        )
        row = cur.fetchone()
    insert_audit(
        conn,
        profile=context.profile,
        account_id=rep_account_id,
        action="draft_outcome_recorded",
        target_type="case",
        target_id=case_id,
        details={"outcome": outcome, "edit_distance_ratio": edit_distance_ratio},
    )
    return serialize_row(row)


def _list_feedback(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    """Supervisor Admin's bounded read over BOTH feedback tables (S10, FR-3).

    Split-by-table (not a merged/unified list): ``reason_tags`` stays a
    first-class column on each row rather than flattened into prose, which is
    what makes this aggregation-friendly for Phase 2. A read -> no actor
    required, no audit row (parity with ``list_agent_experience`` /
    ``dead_letter._list_dead_letters`` -- see the module docstring for the
    per-tool-allowlist note this handler's registration relies on).
    """
    # Profile gate (shared with the mock twin): allowlisting is per-TOOL, so
    # toee_feedback also sits on internal_copilot for the three writes -- which
    # left this read reachable from that profile. No actor is required (read
    # parity with list_agent_experience), but the profile axis is enforced.
    resolve_list_feedback_authorization(context)
    since = _read_since_filter(params)
    verdict = _read_verdict_filter(params)
    limit = _read_list_limit(params)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT {_REVIEW_COLUMNS}
            FROM interaction_review
            WHERE (%(since)s::timestamptz IS NULL OR created_at >= %(since)s::timestamptz)
              AND (%(verdict)s::text IS NULL OR verdict = %(verdict)s)
            ORDER BY created_at DESC, id DESC
            LIMIT %(limit)s
            """,
            {"since": since, "verdict": verdict, "limit": limit},
        )
        reviews = [serialize_row(row) for row in cur.fetchall()]

        cur.execute(
            f"""
            SELECT {_DRAFT_RATING_COLUMNS}
            FROM draft_feedback
            WHERE (%(since)s::timestamptz IS NULL OR created_at >= %(since)s::timestamptz)
              AND (%(verdict)s::text IS NULL OR verdict = %(verdict)s)
            ORDER BY created_at DESC, id DESC
            LIMIT %(limit)s
            """,
            {"since": since, "verdict": verdict, "limit": limit},
        )
        drafts = [serialize_row(row) for row in cur.fetchall()]

    return {"interaction_reviews": reviews, "draft_feedback": drafts}


def feedback_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for ``toee_feedback`` (S03/S06/S08/S10 complete)."""
    return {
        "toee_feedback": {
            "submit_interaction_review": _submit_interaction_review,
            "submit_draft_rating": _submit_draft_rating,
            "record_draft_outcome": _record_draft_outcome,
            "list_feedback": _list_feedback,
        }
    }
