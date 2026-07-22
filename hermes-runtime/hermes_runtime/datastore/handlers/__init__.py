"""Postgres datastore handler registry (mirrors the MockDriver registry shape).

Each handler is ``(conn, params, context) -> JSON-serializable`` and runs real SQL
against the Toee Business Datastore (ADR-0140). The PostgresDriver dispatches on
``(tool, action)`` exactly like the mock path, so the governed contract is
identical; only the backend differs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from .accounts import account_handlers
from .agent_experience import agent_experience_handlers
from .cases import case_handlers
from .dead_letter import dead_letter_handlers
from .eval_review import eval_review_handlers
from .identity import identity_handlers
from .knowledge import knowledge_handlers
from .memory import memory_handlers
from .metrics import metrics_handlers
from .retention import retention_handlers

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext

# (conn, params, context) -> JSON-serializable result.
DatastoreHandler = Callable[[Any, dict[str, Any], "ToolExecutionContext"], Any]
DatastoreRegistry = dict[str, dict[str, DatastoreHandler]]


def _merge(*fragments: DatastoreRegistry) -> DatastoreRegistry:
    merged: DatastoreRegistry = {}
    for fragment in fragments:
        for tool, actions in fragment.items():
            merged.setdefault(tool, {}).update(actions)
    return merged


def build_datastore_registry() -> DatastoreRegistry:
    """Merge all per-tool datastore handler fragments into one registry."""
    return _merge(
        case_handlers(),
        memory_handlers(),
        identity_handlers(),
        account_handlers(),
        knowledge_handlers(),
        eval_review_handlers(),
        agent_experience_handlers(),
        metrics_handlers(),
        retention_handlers(),
        dead_letter_handlers(),
    )


__all__ = ["DatastoreHandler", "DatastoreRegistry", "build_datastore_registry"]
