"""Mock handlers for ``toee_feedback`` (0.0.4 S02, ADR-0154 tool shell).

This slice ships the catalog/schema/allowlist/exclusion shell only -- no
migration, no real persistence (S03/S06/S08/S10 add the ``interaction_review``
and ``draft_feedback`` tables and their Postgres handlers). Mirrors
``toee_retention``'s mock twin: there is no store behind the mock fragment, so
every action returns an honest "nothing persisted / nothing here yet" shape,
never a fabricated id or row (same discipline as
``enqueue_corpus_reingest``/``initiate_reconnect`` returning "unavailable").
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .driver import MockHandlerRegistry

if TYPE_CHECKING:
    from ...tool_gate import ToolExecutionContext


def create_feedback_mock_handlers() -> MockHandlerRegistry:
    """Mock handlers for ``toee_feedback`` -- never LLM-callable (all four
    actions are agent-excluded, see ``toee_hermes.plugin._AGENT_EXCLUDED_ACTIONS``).
    """

    def submit_interaction_review(
        params: dict[str, Any], context: "ToolExecutionContext"
    ) -> dict[str, Any]:
        return {"review_id": None, "status": "unavailable"}

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
