"""Governed dispatch (ports execute-tool.ts).

`execute_tool` validates tool/action against the v1 catalog, runs the Tool Gate
before any driver call, invokes the driver, and emits audit metadata. Any unknown
tool/action, gate denial, or driver failure becomes a governed failure — never a
raised exception and never a fabricated result (ADR-0020, ADR-0136).
"""

from toee_hermes.errors import ToolDriverError
from toee_hermes.execute import (
    TOOL_UNAVAILABLE_MESSAGE,
    ToolRequest,
    execute_tool,
)
from toee_hermes.tool_gate import GateDecision, ToolExecutionContext, allow_all_gate


class RecordingDriver:
    """A real (non-mock) ToolDriver test double at the driver boundary."""

    kind = "mock"

    def __init__(self, *, result=None, error=None):
        self._result = result
        self._error = error
        self.calls: list[ToolRequest] = []

    def execute(self, request: ToolRequest, context: ToolExecutionContext):
        self.calls.append(request)
        if self._error is not None:
            raise self._error
        return self._result


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext(
        profile="customer_service_external",
        user_id="u1",
        connected_account_id="ca1",
    )


def test_unknown_tool_is_governed_failure_without_calling_driver() -> None:
    driver = RecordingDriver()
    result = execute_tool(
        tool="toee_nope", action="whatever", context=_ctx(), driver=driver
    )

    assert result.ok is False
    assert result.error_class == "unknown_tool"
    assert result.audit.outcome == "unavailable"
    assert result.audit.tool == "toee_nope"
    assert driver.calls == []


def test_unknown_action_is_governed_failure_without_calling_driver() -> None:
    driver = RecordingDriver()
    result = execute_tool(
        tool="toee_identity_lookup",
        action="get_order",
        context=_ctx(),
        driver=driver,
    )

    assert result.ok is False
    assert result.error_class == "unknown_action"
    assert driver.calls == []


def test_gate_denial_blocks_before_driver_and_keeps_message() -> None:
    driver = RecordingDriver()

    def deny_gate(request: ToolRequest, context: ToolExecutionContext):
        return GateDecision(
            allow=False,
            error_class="policy_blocked",
            message="tool not in profile allowlist",
        )

    result = execute_tool(
        tool="toee_identity_lookup",
        action="match_phone",
        context=_ctx(),
        driver=driver,
        gate=deny_gate,
    )

    assert result.ok is False
    assert result.error_class == "policy_blocked"
    assert result.message == "tool not in profile allowlist"
    assert driver.calls == []


def test_success_passes_driver_data_through_and_audits_ok() -> None:
    driver = RecordingDriver(result={"outcome": "unmatched_caller"})
    records = []

    result = execute_tool(
        tool="toee_identity_lookup",
        action="match_phone",
        params={"phone": "+14165550000"},
        context=_ctx(),
        driver=driver,
        audit=records.append,
    )

    assert result.ok is True
    assert result.data == {"outcome": "unmatched_caller"}
    assert result.audit.outcome == "ok"
    assert result.audit.driver == "mock"
    assert result.audit.user_id == "u1"
    assert result.audit.connected_account_id == "ca1"
    assert records == [result.audit]
    assert driver.calls[0].params == {"phone": "+14165550000"}


def test_tool_driver_error_maps_class_and_hides_raw_message() -> None:
    driver = RecordingDriver(
        error=ToolDriverError("auth_expired", "composio token expired for ca1")
    )

    result = execute_tool(
        tool="toee_identity_lookup",
        action="match_phone",
        context=_ctx(),
        driver=driver,
    )

    assert result.ok is False
    assert result.error_class == "auth_expired"
    assert result.message == TOOL_UNAVAILABLE_MESSAGE
    assert "composio" not in result.message
    assert result.audit.outcome == "unavailable"
    assert result.audit.error_class == "auth_expired"


def test_unexpected_driver_exception_is_unexpected_error() -> None:
    driver = RecordingDriver(error=RuntimeError("boom stack trace"))

    result = execute_tool(
        tool="toee_identity_lookup",
        action="match_phone",
        context=_ctx(),
        driver=driver,
    )

    assert result.ok is False
    assert result.error_class == "unexpected_error"
    assert result.message == TOOL_UNAVAILABLE_MESSAGE
    assert "boom" not in result.message


def test_allow_all_gate_allows_any_request() -> None:
    decision = allow_all_gate(
        ToolRequest(tool="toee_identity_lookup", action="match_phone", params={}),
        _ctx(),
    )
    assert decision.allow is True
