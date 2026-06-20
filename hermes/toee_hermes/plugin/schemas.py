"""Tool schemas exposed to the LLM (Hermes plugin contract).

Each v1 Domain Adapter Tool action (ADR-0059/0070 catalog) becomes one Hermes
tool named ``<tool>__<action>`` whose ``toolset`` is the ``toee_*`` tool, so
per-profile allowlisting (ADR-0034/35/38) gates by toolset. Parameters are an
open object: the LLM passes the action's params at the top level and the handler
forwards them to governed dispatch, which validates tool+action against the
catalog. Richer per-action parameter schemas can be layered on later without
changing the registration contract.
"""

from __future__ import annotations

from typing import Any

from ..tool_catalog import TOOL_CATALOG


def hermes_tool_name(tool: str, action: str) -> str:
    """Flat Hermes tool name for a ``(tool, action)`` pair."""
    return f"{tool}__{action}"


def build_tool_schema(tool: str, action: str) -> dict[str, Any]:
    """JSON schema for one ``(tool, action)`` the model can call."""
    return {
        "name": hermes_tool_name(tool, action),
        "description": (
            f'Toee Domain Adapter Tool "{tool}", action "{action}". '
            "Pass the action's parameters as top-level fields. Returns governed "
            "JSON; on failure an object with an \"error\" message and "
            '"error_class" (never raw vendor errors, never fabricated data).'
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        },
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
