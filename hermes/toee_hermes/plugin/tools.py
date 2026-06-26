"""Tool handlers bridging the Hermes contract to governed dispatch (ADR-0139).

A Hermes tool handler is ``def h(args: dict, **kwargs) -> str``: it must always
return a JSON string and never raise (the agent's tool loop depends on this).
:func:`make_tool_handler` binds one ``(tool, action)`` to :func:`execute_tool`,
so every call runs the catalog check, the Tool Gate, the driver, and audit, then
serializes the governed :class:`ToolResult`: success data on ``ok``, and an
``{"error", "error_class"}`` object otherwise (ADR-0020, ADR-0136) — never a raw
vendor error and never fabricated data.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from ..drivers.base import IntegrationDriver  # noqa: F401  (re-exported intent)
from ..errors import ToolErrorClass
from ..execute import AuditSink, ToolDriver, ToolResult, execute_tool
from ..tool_gate import ToolExecutionContext, ToolGate
from .schemas import hermes_tool_name

# Builds the execution context from the runtime kwargs Hermes passes the handler
# (e.g. session/task identifiers). Identity/profile wiring is injected by the
# embedding layer; the default provider supplies the profile only.
ContextProvider = Callable[[dict[str, Any]], ToolExecutionContext]

_INTERNAL_ERROR_MESSAGE = "The requested system is temporarily unavailable."


def serialize_result(result: ToolResult) -> str:
    """Serialize a governed :class:`ToolResult` to the JSON string Hermes expects."""
    if result.ok:
        try:
            return json.dumps(result.data)
        except (TypeError, ValueError):
            return json.dumps(
                {
                    "error": _INTERNAL_ERROR_MESSAGE,
                    "error_class": "unexpected_error",
                }
            )
    return json.dumps({"error": result.message, "error_class": result.error_class})


def make_tool_handler(
    *,
    tool: str,
    action: str,
    driver: ToolDriver,
    context_provider: ContextProvider,
    gate: Optional[ToolGate] = None,
    audit: Optional[AuditSink] = None,
) -> Callable[..., str]:
    """Bind ``(tool, action)`` to a Hermes handler over governed dispatch."""

    def handler(args: Optional[dict[str, Any]] = None, **kwargs: Any) -> str:
        params = dict(args or {})
        try:
            context = context_provider(kwargs)
            result = execute_tool(
                tool=tool,
                action=action,
                context=context,
                driver=driver,
                params=params,
                gate=gate,
                audit=audit,
            )
        except Exception:
            # execute_tool already governs driver failures; this guards the
            # context provider and any serialization edge so the handler never
            # raises into the agent's tool loop.
            error_class: ToolErrorClass = "unexpected_error"
            return json.dumps(
                {"error": _INTERNAL_ERROR_MESSAGE, "error_class": error_class}
            )
        return serialize_result(result)

    handler.__name__ = hermes_tool_name(tool, action)
    return handler
