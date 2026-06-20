"""Mock integration driver (ports mock-driver.ts).

Holds a registry of per-tool, per-action handlers. Used by local dev and the
Launch Eval runner (ADR-0137). A catalog-valid request with no registered
handler is a configuration gap and surfaces as a governed failure, never a raise
that escapes dispatch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from ...errors import ToolDriverError

if TYPE_CHECKING:
    from ...execute import ToolRequest
    from ...tool_gate import ToolExecutionContext

# tool name -> action -> handler(params, context) -> JSON-serializable result.
# Handlers receive the execution context (faithful to the TS `(params, context)`
# handlers) so identity-scoped reads can consult the Session Identity Snapshot at
# ``context.identity`` (ADR-0043) rather than smuggling it through ``params``.
MockHandler = Callable[[dict[str, Any], "ToolExecutionContext"], Any]
MockHandlerRegistry = dict[str, dict[str, MockHandler]]


def merge_registries(*fragments: MockHandlerRegistry) -> MockHandlerRegistry:
    """Merge per-tool registry fragments into one registry.

    Later fragments win on a tool/action collision. Each tool's action map is
    copied so callers cannot mutate a fragment by mutating the result.
    """
    merged: MockHandlerRegistry = {}
    for fragment in fragments:
        for tool, actions in fragment.items():
            merged.setdefault(tool, {}).update(actions)
    return merged


class MockDriver:
    kind = "mock"

    def __init__(self, handlers: MockHandlerRegistry) -> None:
        self._handlers = handlers

    def execute(self, request: "ToolRequest", context: "ToolExecutionContext") -> Any:
        actions = self._handlers.get(request.tool)
        if actions is None:
            raise ToolDriverError(
                "configuration_missing",
                f"No mock handlers registered for tool '{request.tool}'.",
            )
        handler = actions.get(request.action)
        if handler is None:
            raise ToolDriverError(
                "configuration_missing",
                f"No mock handler registered for '{request.tool}.{request.action}'.",
            )
        return handler(request.params, context)
