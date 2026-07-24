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

``submit_draft_rating`` (0.0.4 S06, ADR-0154, FR-1/2/4/NFR-2/5) is the
INTERNAL mechanism: a rep's thumbs-up / thumbs-down judgment on one Copilot
Draft Action draft, down carrying at least one INTERNAL Review Reason Tag.
Same governance shape as submit_interaction_review (fail-closed actor,
validate-then-append), PLUS a case-ownership gate -- the acting rep must hold
the case the draft belongs to. That ownership check needs the real cases
table, so it is enforced ONLY in the Postgres handler (mirrors
``_send_sms_message``'s assignee check in ``datastore/handlers/cases.py``);
this mock has no case store to check against, same as the ``toee_case_manage``
mock stubs (``admin_stubs.py``) never enforce it either.

``record_draft_outcome`` (0.0.4 S08, ADR-0154, FR-1/4/9/NFR-2) is the
IMPLICIT counterpart to ``submit_draft_rating``: whether the rep sent the
generated draft untouched (``sent_as_is``) or edited it first
(``sent_edited`` + a normalized edit-distance ratio), written into the SAME
``draft_feedback`` table (no verdict/tags -- this mechanism records an
outcome, not a judgment). Reuses ``resolve_draft_rating_authorization`` and
the case-ownership gate verbatim -- an outcome write is governed exactly like
a rating write, just a different payload shape.

``list_feedback`` (0.0.4 S10, ADR-0154, FR-3 read half) is the Supervisor
Admin's governed READ over BOTH tables at once: interaction_review rows keyed
by subject, draft_feedback rows keyed by case + draft_correlation_id. It is
the seam Phase 2's aggregation will consume and the way an admin inspects
either table through dispatch today without a database client. Bounded
(``_LIST_FEEDBACK_LIMIT``) with two optional filters (``since``, ``verdict``)
shared with the Postgres handler -- see the validators below. Read-only: no
actor is required and no audit row is written (parity with
``list_agent_experience``/``list_dead_letters`` -- a read is not a governed
action).
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

# submit_draft_rating (S06): draft_kind spans the three Copilot Draft Action
# surfaces; a rating verdict is thumbs up/down (distinct from the pass/fail
# vocabulary above -- ADR-0154 keeps the two mechanisms' verdict enums separate
# too).
DRAFT_KINDS: tuple[str, ...] = ("sms", "email", "note")
DRAFT_RATING_VERDICTS: tuple[str, ...] = ("up", "down")


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


def _require_case_id(params: dict[str, Any]) -> str:
    case_id = params.get("case_id")
    if not isinstance(case_id, str) or not case_id.strip():
        raise ToolDriverError(
            "unexpected_error",
            "submit_draft_rating requires a non-empty string case_id.",
        )
    return case_id


def _require_draft_correlation_id(params: dict[str, Any]) -> str:
    draft_correlation_id = params.get("draft_correlation_id")
    if not isinstance(draft_correlation_id, str) or not draft_correlation_id.strip():
        raise ToolDriverError(
            "unexpected_error",
            "submit_draft_rating requires a non-empty string draft_correlation_id.",
        )
    return draft_correlation_id


def _require_draft_kind(params: dict[str, Any]) -> str:
    draft_kind = params.get("draft_kind")
    if draft_kind not in DRAFT_KINDS:
        raise ToolDriverError(
            "unexpected_error",
            f'submit_draft_rating rejects draft_kind "{draft_kind}"; only '
            f"{DRAFT_KINDS} are allowed.",
        )
    return draft_kind


def _require_draft_rating_verdict(params: dict[str, Any]) -> str:
    # Genuinely caller-supplied (the rep's actual thumbs up/down), unlike the
    # ACTOR below, which is always framework-derived.
    verdict = params.get("verdict")
    if verdict not in DRAFT_RATING_VERDICTS:
        raise ToolDriverError(
            "unexpected_error",
            f'submit_draft_rating rejects verdict "{verdict}"; only '
            f"{DRAFT_RATING_VERDICTS} are allowed.",
        )
    return verdict


def _read_internal_reason_tags(params: dict[str, Any], *, verdict: str) -> list[str]:
    """Validate ``reason_tags`` against the INTERNAL Review Reason Tag set.

    A ``down`` verdict must carry at least one tag (DB-level CHECK backs this
    up, 0019_draft_feedback.sql); every tag must belong to the internal set --
    a tag from the external (interaction-review) set is a validation error,
    since the two enums are deliberately separate (ADR-0154).
    """
    # Lazy import, same reason as _read_reason_tags above (breaks the
    # plugin/__init__ <-> drivers.mock circular import).
    from ...plugin.schemas import INTERNAL_REVIEW_REASON_TAGS

    raw_tags = params.get("reason_tags")
    if raw_tags is None:
        tags: list[str] = []
    elif isinstance(raw_tags, list) and all(isinstance(t, str) for t in raw_tags):
        tags = raw_tags
    else:
        raise ToolDriverError(
            "unexpected_error",
            "submit_draft_rating requires reason_tags to be a list of strings.",
        )
    unknown = [t for t in tags if t not in INTERNAL_REVIEW_REASON_TAGS]
    if unknown:
        raise ToolDriverError(
            "unexpected_error",
            f"submit_draft_rating rejects unknown reason tag(s) {unknown}; "
            f"only the internal Review Reason Tag set {INTERNAL_REVIEW_REASON_TAGS} "
            "is allowed here.",
        )
    if verdict == "down" and not tags:
        raise ToolDriverError(
            "unexpected_error",
            "submit_draft_rating requires at least one reason tag when "
            "verdict is down.",
        )
    return tags


def _read_rating_comment(params: dict[str, Any]) -> Optional[str]:
    comment = params.get("comment")
    if comment is None:
        return None
    if not isinstance(comment, str):
        raise ToolDriverError(
            "unexpected_error", "submit_draft_rating comment must be a string."
        )
    return comment


def _require_draft_text(params: dict[str, Any]) -> str:
    # S06 review (Important): a rated_only row has no linked outcome row to
    # join against (record_draft_outcome only fires on an actual send), so if
    # draft_text isn't captured HERE, a down-rating's generated draft is lost
    # forever -- a supervisor sees the tags but never what was written.
    # Always available in practice: you rate the draft card, so its text is
    # always in hand -- required, same as case_id/draft_correlation_id above.
    draft_text = params.get("draft_text")
    if not isinstance(draft_text, str) or not draft_text.strip():
        raise ToolDriverError(
            "unexpected_error",
            "submit_draft_rating requires a non-empty string draft_text.",
        )
    return draft_text


# record_draft_outcome (S08): the implicit counterpart to a rating verdict --
# whether the rep sent the draft as generated or edited it first.
DRAFT_OUTCOMES: tuple[str, ...] = ("sent_as_is", "sent_edited")


def _require_draft_outcome(params: dict[str, Any]) -> str:
    outcome = params.get("outcome")
    if outcome not in DRAFT_OUTCOMES:
        raise ToolDriverError(
            "unexpected_error",
            f'record_draft_outcome rejects outcome "{outcome}"; only '
            f"{DRAFT_OUTCOMES} are allowed.",
        )
    return outcome


def _read_edit_distance_ratio(
    params: dict[str, Any], *, outcome: str
) -> Optional[float]:
    """Required exactly when ``outcome`` is ``sent_edited``, rejected otherwise.

    A ``sent_as_is`` outcome with a ratio attached is a contradiction (nothing
    was edited, so there is nothing to measure) -- reject it rather than
    silently drop it, same "reject, don't coerce" discipline as the reason-tag
    set checks above.
    """
    ratio = params.get("edit_distance_ratio")
    if outcome == "sent_edited":
        if not isinstance(ratio, (int, float)) or isinstance(ratio, bool):
            raise ToolDriverError(
                "unexpected_error",
                "record_draft_outcome requires a numeric edit_distance_ratio "
                "when outcome is sent_edited.",
            )
        return float(ratio)
    if ratio is not None:
        raise ToolDriverError(
            "unexpected_error",
            "record_draft_outcome rejects edit_distance_ratio when outcome is "
            "sent_as_is.",
        )
    return None


# list_feedback (S10): bounded-read filters, shared with the Postgres handler
# (imported verbatim, same "one resolver, both twins" discipline as the write
# validators above) so the two backends can't drift on what a valid filter is.

# ponytail: a fixed cap, not a cursor/pagination scheme -- this is a supervisor
# triage read, not a bulk export. Add a cursor the day someone needs page 2.
_LIST_FEEDBACK_LIMIT = 50


def _read_since_filter(params: dict[str, Any]) -> Optional[str]:
    """Optional ISO-8601 lower bound on ``created_at``, validated up front.

    Reject rather than silently ignore a malformed value (same "reject, don't
    coerce" discipline as ``_read_edit_distance_ratio`` above) -- a typo'd
    filter should fail loudly, not quietly return everything.
    """
    since = params.get("since")
    if since is None:
        return None
    if not isinstance(since, str):
        raise ToolDriverError(
            "unexpected_error", "list_feedback requires since to be a string."
        )
    try:
        datetime.fromisoformat(since)
    except ValueError as exc:
        raise ToolDriverError(
            "unexpected_error",
            f'list_feedback rejects since "{since}": not a valid ISO-8601 timestamp.',
        ) from exc
    return since


def _read_verdict_filter(params: dict[str, Any]) -> Optional[str]:
    """Optional verdict filter spanning BOTH mechanisms' vocabularies at once.

    Deliberately NOT enum-checked against either single set (unlike
    ``_require_verdict``/``_require_draft_rating_verdict``): one param filters
    both tables in the same call, and each table's own verdict column only
    ever holds its own vocabulary anyway, so an unmatched value just yields no
    rows from that table rather than needing a combined enum here.
    """
    verdict = params.get("verdict")
    if verdict is None:
        return None
    if not isinstance(verdict, str):
        raise ToolDriverError(
            "unexpected_error", "list_feedback requires verdict to be a string."
        )
    return verdict


def _read_list_limit(params: dict[str, Any]) -> int:
    """Bounded page size: caller-supplied, clamped to the cap, never above it."""
    limit = params.get("limit")
    if limit is None:
        return _LIST_FEEDBACK_LIMIT
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ToolDriverError(
            "unexpected_error", "list_feedback requires limit to be a positive integer."
        )
    return min(limit, _LIST_FEEDBACK_LIMIT)


def resolve_draft_rating_authorization(context: "ToolExecutionContext") -> str:
    """Framework-derived ``rep_account_id`` for submit_draft_rating.

    Same fail-closed shape as ``resolve_interaction_review_authorization``
    (internal_copilot profile + an attributed ``context.user_id``) -- kept as
    its own function rather than a shared call so each governed action's gate
    reads standalone and a future edit to one can't silently change the
    other's behavior. The additional case-ownership gate this mechanism
    requires lives in the Postgres handler only (see module docstring).
    """
    from ...plugin.profiles import INTERNAL

    if context.profile != INTERNAL:
        raise ToolDriverError(
            "policy_blocked",
            f'draft ratings are not permitted for profile "{context.profile}".',
        )
    if not context.user_id:
        raise ToolDriverError(
            "policy_blocked",
            "A governed draft rating requires an attributed rep.",
        )
    return context.user_id


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
    draft_ratings: list[dict[str, Any]] = []

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
        # Same gate-first ordering as submit_draft_rating: a missing/
        # unauthorized actor is ALWAYS policy_blocked before anything else is
        # read. Reuses that resolver verbatim (S08 brief) -- an outcome write
        # is governed exactly like a rating write, just a different payload.
        rep_account_id = resolve_draft_rating_authorization(context)
        case_id = _require_case_id(params)
        draft_correlation_id = _require_draft_correlation_id(params)
        draft_kind = _require_draft_kind(params)
        outcome = _require_draft_outcome(params)
        draft_text = _require_draft_text(params)
        edit_distance_ratio = _read_edit_distance_ratio(params, outcome=outcome)

        entry = {
            "id": f"draft_{len(draft_ratings) + 1}",
            "case_id": case_id,
            "draft_correlation_id": draft_correlation_id,
            "draft_kind": draft_kind,
            "draft_text": draft_text,
            "outcome": outcome,
            "edit_distance_ratio": edit_distance_ratio,
            "verdict": None,
            "reason_tags": [],
            "comment": None,
            "rep_account_id": rep_account_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        # Same store as submit_draft_rating: rows from both actions share the
        # draft_correlation_id, so one draft's implicit + explicit signals join.
        draft_ratings.append(entry)
        return dict(entry)

    def submit_draft_rating(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # The gate runs FIRST -- same ordering discipline as
        # submit_interaction_review above: a missing/unauthorized actor is
        # ALWAYS policy_blocked before anything else is even read, let alone
        # validated or stored.
        rep_account_id = resolve_draft_rating_authorization(context)
        case_id = _require_case_id(params)
        draft_correlation_id = _require_draft_correlation_id(params)
        draft_kind = _require_draft_kind(params)
        verdict = _require_draft_rating_verdict(params)
        reason_tags = _read_internal_reason_tags(params, verdict=verdict)
        comment = _read_rating_comment(params)
        draft_text = _require_draft_text(params)

        entry = {
            "id": f"draft_{len(draft_ratings) + 1}",
            "case_id": case_id,
            "draft_correlation_id": draft_correlation_id,
            "draft_kind": draft_kind,
            "draft_text": draft_text,
            "outcome": "rated_only",
            "edit_distance_ratio": None,
            "verdict": verdict,
            "reason_tags": reason_tags,
            "comment": comment,
            "rep_account_id": rep_account_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        draft_ratings.append(entry)
        return dict(entry)

    def list_feedback(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        # Read-only (S10): no actor required, no audit row -- see the module
        # docstring and resolve_*_authorization's precedent for why a read
        # isn't a governed action the way the three writes above are.
        del context
        since = _read_since_filter(params)
        verdict = _read_verdict_filter(params)
        limit = _read_list_limit(params)

        def _matches(entry: dict[str, Any]) -> bool:
            if since is not None and datetime.fromisoformat(
                entry["created_at"]
            ) < datetime.fromisoformat(since):
                return False
            if verdict is not None and entry.get("verdict") != verdict:
                return False
            return True

        reviews = sorted(
            (dict(e) for e in store if _matches(e)),
            key=lambda e: e["created_at"],
            reverse=True,
        )
        drafts = sorted(
            (dict(e) for e in draft_ratings if _matches(e)),
            key=lambda e: e["created_at"],
            reverse=True,
        )
        return {
            "interaction_reviews": reviews[:limit],
            "draft_feedback": drafts[:limit],
        }

    return {
        "toee_feedback": {
            "submit_interaction_review": submit_interaction_review,
            "record_draft_outcome": record_draft_outcome,
            "submit_draft_rating": submit_draft_rating,
            "list_feedback": list_feedback,
        }
    }
