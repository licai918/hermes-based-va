"""Eval-recording registration for a Launch Eval turn (ADR-0071, ADR-0139).

``register_eval(ctx, driver=..., gate=..., identity=...)`` registers the External
profile's allowlisted tools exactly like ``register`` but injects the scenario's
MockDriver, External-profile Tool Gate, and the closed-over Session Identity
Snapshot (ADR-0043), so a recorded live turn dispatches through the scenario's
mock data and policy without the agent loop supplying a per-call identity kwarg.

These run the real governed dispatch (:func:`execute_tool`) through a faithful
``RecordingCtx`` and a recording driver — no fabricated handler.
"""

from __future__ import annotations

import json
from typing import Any

from toee_hermes.execute import ToolRequest
from toee_hermes.plugin import register_eval
from toee_hermes.plugin.profiles import EXTERNAL
from toee_hermes.tool_gate import GateDecision, ToolExecutionContext, allow_all_gate


class RecordingCtx:
    """Minimal faithful stand-in for the Hermes plugin registration context."""

    def __init__(self, profile: str | None = None) -> None:
        self.profile = profile
        self.tools: list[dict[str, Any]] = []
        self.hooks: list[tuple[str, Any]] = []

    def register_tool(self, *, name: str, toolset: str, schema: dict, handler: Any) -> None:
        self.tools.append(
            {"name": name, "toolset": toolset, "schema": schema, "handler": handler}
        )

    def register_hook(self, event: str, callback: Any) -> None:
        self.hooks.append((event, callback))


class RecordingDriver:
    """A ``ToolDriver`` that records the ``(request, context)`` it dispatched."""

    kind = "mock"

    def __init__(self) -> None:
        self.calls: list[tuple[ToolRequest, ToolExecutionContext]] = []

    def execute(self, request: ToolRequest, context: ToolExecutionContext) -> Any:
        self.calls.append((request, context))
        return {"echo": request.action}


def _handler(ctx: RecordingCtx, name: str) -> Any:
    return next(tool for tool in ctx.tools if tool["name"] == name)["handler"]


def test_register_eval_threads_session_identity_into_governed_dispatch() -> None:
    ctx = RecordingCtx(profile=EXTERNAL)
    driver = RecordingDriver()
    identity = {"customer_id": "cust-1", "match": "verified"}

    register_eval(ctx, driver=driver, gate=allow_all_gate, identity=identity)

    out = json.loads(
        _handler(ctx, "toee_shopify_read__get_order")({"order_id": "1042"})
    )

    assert out == {"echo": "get_order"}
    assert len(driver.calls) == 1
    request, context = driver.calls[0]
    assert request.tool == "toee_shopify_read"
    # The agent loop never passes identity; the scenario snapshot is closed over.
    assert context.identity == identity
    assert context.profile == EXTERNAL


def test_register_eval_applies_the_injected_gate_before_the_driver() -> None:
    ctx = RecordingCtx(profile=EXTERNAL)
    driver = RecordingDriver()

    def deny_qbo(request: ToolRequest, context: ToolExecutionContext) -> GateDecision:
        if request.tool == "toee_qbo_read":
            return GateDecision(
                allow=False, error_class="policy_blocked", message="blocked"
            )
        return GateDecision(allow=True)

    register_eval(ctx, driver=driver, gate=deny_qbo, identity=None)

    blocked = json.loads(
        _handler(ctx, "toee_qbo_read__get_invoice")({"invoice_id": "INV-9001"})
    )
    allowed = json.loads(
        _handler(ctx, "toee_shopify_read__get_order")({"order_id": "1042"})
    )

    assert blocked["error_class"] == "policy_blocked"
    assert "error_class" not in allowed
    # The gate denied qbo before the driver ran, so only shopify reached the driver.
    assert [request.tool for request, _ in driver.calls] == ["toee_shopify_read"]


def test_register_eval_registers_only_the_external_allowlist() -> None:
    ctx = RecordingCtx(profile=EXTERNAL)

    register_eval(ctx, driver=RecordingDriver(), gate=allow_all_gate, identity={})

    toolsets = {tool["toolset"] for tool in ctx.tools}
    assert "toee_textline_reply" in toolsets
    assert "toee_shopify_read" in toolsets
    # Copilot/admin-only toolsets are outside the External allowlist (default-deny).
    assert "toee_copilot_draft" not in toolsets
    assert "toee_workbench_admin" not in toolsets
