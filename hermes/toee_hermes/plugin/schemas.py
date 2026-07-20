"""Tool schemas exposed to the LLM (Hermes plugin contract).

Each v1 Domain Adapter Tool action (ADR-0059/0070 catalog) becomes one Hermes
tool named ``<tool>__<action>`` whose ``toolset`` is the ``toee_*`` tool, so
per-profile allowlisting (ADR-0034/35/38) gates by toolset. Parameters default
to an open object -- the LLM passes the action's params at the top level and
the handler forwards them to governed dispatch, which validates tool+action
against the catalog -- but an open `{}` schema means the model has to guess
param names from persona prose, which is non-deterministic per call (the S10
``search_public_site`` incident: same process, same turn shape, guessed
``{"query": ...}`` once and an empty/wrong payload the next). ``PARAM_SCHEMAS``
layers real ``properties``/``required`` onto specific actions so the model
sees the param names instead of guessing; ``additionalProperties`` stays
``True`` throughout since governed dispatch -- not this schema -- validates
tool+action against the catalog.
"""

from __future__ import annotations

from typing import Any

from ..tool_catalog import TOOL_CATALOG

# Known (tool, action) -> {"properties": ..., "required": [...]} overrides.
# Populated only for actions with a diagnosed param-guessing failure so far
# (S10). Filling the rest of the catalog -- notably the get_order family
# from the 0.0.2 {order_id vs order_number} incident -- is tracked debt, not
# this fix's scope; add entries here as they're diagnosed.
PARAM_SCHEMAS: dict[tuple[str, str], dict[str, Any]] = {
    ("toee_knowledge_search", "search_public_site"): {
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "The customer's question or topic to search the public "
                    "knowledge corpus for."
                ),
            }
        },
        "required": ["query"],
    },
    ("toee_knowledge_search", "search_operational_policy"): {
        "properties": {
            "query": {
                "type": "string",
                "description": "Policy topic or question.",
            },
            "slot": {
                "type": "string",
                "description": "Operational policy slot identifier, when known.",
            },
        },
        # Neither is required -- the mock driver accepts either (slot first,
        # falling back to query).
    },
}


def hermes_tool_name(tool: str, action: str) -> str:
    """Flat Hermes tool name for a ``(tool, action)`` pair."""
    return f"{tool}__{action}"


def build_tool_schema(tool: str, action: str) -> dict[str, Any]:
    """JSON schema for one ``(tool, action)`` the model can call.

    Merges :data:`PARAM_SCHEMAS` for known actions; falls back to today's
    open object (empty ``properties``, no ``required``) otherwise.
    """
    layered = PARAM_SCHEMAS.get((tool, action), {})
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": layered.get("properties", {}),
        "additionalProperties": True,
    }
    if layered.get("required"):
        parameters["required"] = layered["required"]

    return {
        "name": hermes_tool_name(tool, action),
        "description": (
            f'Toee Domain Adapter Tool "{tool}", action "{action}". '
            "Pass the action's parameters as top-level fields. Returns governed "
            "JSON; on failure an object with an \"error\" message and "
            '"error_class" (never raw vendor errors, never fabricated data).'
        ),
        "parameters": parameters,
    }


def build_tool_schemas() -> list[dict[str, Any]]:
    """All catalog actions as ``{tool, action, toolset, schema}`` entries."""
    entries: list[dict[str, Any]] = []
    for tool, actions in TOOL_CATALOG.items():
        for action in actions:
            entries.append(
                {
                    "tool": tool,
                    "action": action,
                    "toolset": tool,
                    "schema": build_tool_schema(tool, action),
                }
            )
    return entries
