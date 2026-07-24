"""Mock handlers for ``toee_feedback`` (0.0.4 S02 shell, S03 real write path).

``submit_interaction_review`` (ADR-0154, FR-1/2/4/NFR-2/5) is the EXTERNAL
mechanism: a supervisor's pass/fail judgment on one Auto-Handled Interaction
record or one sales_outreach Follow-up Case, reviewed from the read-only audit
views. This is where the module's central governance claim becomes real: a
write with no framework-resolved acting employee persists nothing. Mirrors
``agent_experience``'s "one resolver, both twins" discipline -- the validation
helpers and :func:`resolve_interaction_review_authorization` below are imported
by the Postgres handler (``hermes-runtime/hermes_runtime/datastore/handlers/
feedback.py``) too, so the mock and real datastore can't silently drift on what
counts as a governed rejection.

``record_draft_outcome``/``submit_draft_rating`` (S06/S08) and the real
``list_feedback`` read (S10) stay stubs -- out of scope here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from ...errors import ToolDriverError
from .driver import MockHandlerRegistry

if TYPE_CHECKING:
    from ...tool_gate import ToolExecutionContext

# ADR-0154: the whole-interaction verdict is on the existing audit record
# identity (the audit recordId or the sales_outreach case id), never the
# long-lived thread.
INTERACTION_REVIEW_SUBJECT_KINDS: tuple[str, ...] = (
    "auto_handled_record",
    "sales_outreach_case",
)

INTERACTION_REVIEW_VERDICTS: tuple[str, ...] = ("pass", "fail")


def _require_subject_kind(params: dict[str, Any]) -> str:
    subject_kind = params.get("subject_kind")
    if subject_kind not in INTERACTION_REVIEW_SUBJECT_KINDS:
        raise ToolDriverError(
            "unexpected_error",
            f'submit_interaction_review rejects subject_kind "{subject_kind}"; '
            f"only {INTERACTION_REVIEW_SUBJECT_KINDS} are allowed.",
        )
    return subject_kind


def _require_subject_id(params: dict[str, Any]) -> str:
    subject_id = params.get("subject_id")
    if not isinstance(subject_id, str) or not subject_id.strip():
        raise ToolDriverError(
            "unexpected_error",
            "submit_interaction_review requires a non-empty string subject_id.",
        )
    return subject_id


def _require_verdict(params: dict[str, Any]) -> str:
    # The verdict is the reviewer's actual judgment -- genuinely caller-supplied
    # (there is nothing in the execution context to derive it from), unlike the
    # ACTOR below, which is always framework-derived and never taken from here.
    verdict = params.get("verdict")
    if verdict not in INTERACTION_REVIEW_VERDICTS:
        raise ToolDriverError(
            "unexpected_error",
            f'submit_interaction_review rejects verdict "{verdict}"; only '
            f"{INTERACTION_REVIEW_VERDICTS} are allowed.",
        )
    return verdict


def _read_reason_tags(params: dict[str, Any], *, verdict: str) -> list[str]:
    """Validate ``reason_tags`` against the EXTERNAL Review Reason Tag set.

    A ``fail`` verdict must carry at least one tag (DB-level CHECK backs this
    up, 0018_feedback.sql); every tag must belong to the external set -- a tag
    from the internal (draft-rating) set is a validation error, since the two
    enums are deliberately separate (ADR-0154).
    """
    # Lazy import (mirrors resolve_agent_experience_source's ``from ...plugin.
    # profiles import INTERNAL``): plugin/__init__ imports drivers.mock at
    # module load time, so importing plugin.schemas at THIS module's top level
    # would deadlock the circular import; deferring to call time breaks the cycle.
    from ...plugin.schemas import EXTERNAL_REVIEW_REASON_TAGS

    raw_tags = params.get("reason_tags")
    if raw_tags is None:
        tags: list[str] = []
    elif isinstance(raw_tags, list) and all(isinstance(t, str) for t in raw_tags):
        tags = raw_tags
    else:
        raise ToolDriverError(
            "unexpected_error",
            "submit_interaction_review requires reason_tags to be a list of strings.",
        )
    unknown = [t for t in tags if t not in EXTERNAL_REVIEW_REASON_TAGS]
    if unknown:
        raise ToolDriverError(
            "unexpected_error",
            f"submit_interaction_review rejects unknown reason tag(s) {unknown}; "
            f"only the external Review Reason Tag set {EXTERNAL_REVIEW_REASON_TAGS} "
            "is allowed here.",
        )
    if verdict == "fail" and not tags:
        raise ToolDriverError(
            "unexpected_error",
            "submit_interaction_review requires at least one reason tag when "
            "verdict is fail.",
        )
    return tags


def _read_comment(params: dict[str, Any]) -> Optional[str]:
    comment = params.get("comment")
    if comment is None:
        return None
    if not isinstance(comment, str):
        raise ToolDriverError(
            "unexpected_error", "submit_interaction_review comment must be a string."
        )
    return comment


def resolve_interaction_review_authorization(context: "ToolExecutionContext") -> str:
    """Framework-derived ``reviewer_account_id`` for submit_interaction_review.

    ONE shared resolver for the mock and Postgres datastore handlers (same
    "one resolver, both twins" discipline as ``resolve_experience_decision_
    authorization``), so this governance-critical gate can't drift between the
    two. A review is always a supervisor/admin at the keyboard, reached only
    via the internal_copilot BFF's deterministic ``tools:dispatch`` call (the
    audit routes live under ``/copilot``, ADR-0154) -- never a model-supplied
    param (the tool is agent-excluded, ``_AGENT_EXCLUDED_ACTIONS``), never the
    unbound AI turn (whose ``boot_profile`` structurally carries no
    ``user_id`` -- the AI cannot score itself). No ``context.user_id`` ->
    ``policy_blocked``. Any other profile is fail-closed, defense in depth.
    """
    from ...plugin.profiles import INTERNAL

    if context.profile != INTERNAL:
        raise ToolDriverError(
            "policy_blocked",
            f'interaction reviews are not permitted for profile "{context.profile}".',
        )
    if not context.user_id:
        raise ToolDriverError(
            "policy_blocked",
            "A governed interaction review requires an attributed reviewer.",
        )
    return context.user_id


def create_feedback_mock_handlers() -> MockHandlerRegistry:
    """Mock handlers for ``toee_feedback``. Never LLM-callable (all four
    actions are agent-excluded, see ``toee_hermes.plugin._AGENT_EXCLUDED_ACTIONS``).
    """

    store: list[dict[str, Any]] = []

    def submit_interaction_review(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # The gate runs FIRST so a missing actor is ALWAYS policy_blocked
        # regardless of how malformed the rest of the payload is (same
        # ordering as resolve_experience_decision_authorization in
        # _decide_experience) -- only once an actor is resolved do we bother
        # validating the review content.
        reviewer_account_id = resolve_interaction_review_authorization(context)
        subject_kind = _require_subject_kind(params)
        subject_id = _require_subject_id(params)
        verdict = _require_verdict(params)
        reason_tags = _read_reason_tags(params, verdict=verdict)
        comment = _read_comment(params)

        entry = {
            "id": f"irev_{len(store) + 1}",
            "subject_kind": subject_kind,
            "subject_id": subject_id,
            "verdict": verdict,
            "reason_tags": reason_tags,
            "comment": comment,
            "reviewer_account_id": reviewer_account_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        store.append(entry)
        return dict(entry)

    def record_draft_outcome(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        return {"feedback_id": None, "status": "unavailable"}

    def submit_draft_rating(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        return {"feedback_id": None, "status": "unavailable"}

    def list_feedback(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        return {"interaction_reviews": [], "draft_feedback": []}

    return {
        "toee_feedback": {
            "submit_interaction_review": submit_interaction_review,
            "record_draft_outcome": record_draft_outcome,
            "submit_draft_rating": submit_draft_rating,
            "list_feedback": list_feedback,
        }
    }
