"""Governed Domain Adapter Tool dispatch (ports execute-tool.ts).

Validates the tool/action against the v1 catalog, runs the Tool Gate before any
driver call, invokes the driver, and emits audit metadata. Any unknown
tool/action, gate denial, or driver failure becomes a governed failure rather
than a raised exception or fabricated result (ADR-0020).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from .drivers.base import IntegrationDriver
from .errors import ToolDriverError, ToolErrorClass
from .tool_catalog import is_tool_action, is_tool_name
from .tool_gate import GateDecision, ToolExecutionContext, ToolGate, allow_all_gate

# Customer-facing replies must never expose raw driver, OAuth, or vendor errors
# (ADR-0136). Internal/log messages stay on the audit record only.
TOOL_UNAVAILABLE_MESSAGE = "The requested system is temporarily unavailable."


@dataclass(frozen=True)
class ToolRequest:
    tool: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ToolDriver(Protocol):
    """Executes a validated, gate-approved request against an integration backend."""

    kind: IntegrationDriver

    def execute(self, request: ToolRequest, context: ToolExecutionContext) -> Any: ...


@dataclass(frozen=True)
class ToolAuditRecord:
    """Audit metadata emitted for every tool execution attempt (ADR-0136)."""

    tool: str
    action: str
    driver: IntegrationDriver
    outcome: str  # "ok" | "unavailable"
    error_class: Optional[ToolErrorClass] = None
    user_id: Optional[str] = None
    connected_account_id: Optional[str] = None


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    audit: ToolAuditRecord
    data: Any = None
    error_class: Optional[ToolErrorClass] = None
    message: Optional[str] = None


AuditSink = Callable[[ToolAuditRecord], None]


def execute_tool(
    *,
    tool: str,
    action: str,
    context: ToolExecutionContext,
    driver: ToolDriver,
    params: Optional[dict[str, Any]] = None,
    gate: Optional[ToolGate] = None,
    audit: Optional[AuditSink] = None,
) -> ToolResult:
    active_gate: ToolGate = gate or allow_all_gate
    call_params = params or {}
    emit: AuditSink = audit or (lambda record: None)

    def fail(error_class: ToolErrorClass, message: str) -> ToolResult:
        record = ToolAuditRecord(
            tool=tool,
            action=action,
            driver=driver.kind,
            outcome="unavailable",
            error_class=error_class,
            user_id=context.user_id,
            connected_account_id=context.connected_account_id,
        )
        emit(record)
        return ToolResult(
            ok=False, audit=record, error_class=error_class, message=message
        )

    if not is_tool_name(tool):
        return fail("unknown_tool", f'Unknown tool "{tool}".')

    if not is_tool_action(tool, action):
        return fail(
            "unknown_action", f'Unknown action "{action}" for tool "{tool}".'
        )

    request = ToolRequest(tool=tool, action=action, params=call_params)

    decision: GateDecision = active_gate(request, context)
    if not decision.allow:
        return fail(
            decision.error_class or "policy_blocked",
            decision.message or "Tool request blocked by policy.",
        )

    try:
        data = driver.execute(request, context)
    except ToolDriverError as err:
        return fail(err.error_class, TOOL_UNAVAILABLE_MESSAGE)
    except Exception:
        return fail("unexpected_error", TOOL_UNAVAILABLE_MESSAGE)

    record = ToolAuditRecord(
        tool=tool,
        action=action,
        driver=driver.kind,
        outcome="ok",
        user_id=context.user_id,
        connected_account_id=context.connected_account_id,
    )
    emit(record)
    return ToolResult(ok=True, audit=record, data=data)
