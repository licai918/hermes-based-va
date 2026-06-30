"""Gateway turn registration threads ingress identity (ADR-0043, ADR-0140)."""

from __future__ import annotations

import json
from typing import Any

from toee_hermes.plugin import register_turn
from toee_hermes.plugin.profiles import EXTERNAL


class RecordingCtx:
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


def _shopify_handler(ctx: RecordingCtx) -> Any:
    return next(
        tool for tool in ctx.tools if tool["name"] == "toee_shopify_read__get_order"
    )["handler"]


def test_register_turn_threads_identity_into_tools_and_pre_llm_call(monkeypatch) -> None:
    monkeypatch.setenv("INTEGRATION_DRIVER", "mock")
    ctx = RecordingCtx(profile=EXTERNAL)
    identity = {
        "outcome": "verified_customer",
        "shopify_customer_id": "gid://shopify/Customer/1001",
        "company_name": "Hello",
        "resolved_at": "2026-06-30T12:00:00Z",
    }

    register_turn(
        ctx,
        conversation_id="conv-778",
        sms_session_id="sms_session:thr:conv-778",
        identity=identity,
    )

    out = json.loads(_shopify_handler(ctx)({"order_number": "1042"}))
    assert "error_class" not in out

    hook = next(cb for event, cb in ctx.hooks if event == "pre_llm_call")
    injected = hook(session_id="sms_session:thr:conv-778")
    assert injected is not None
    assert "Hello" in injected["context"]
    assert "1001" in injected["context"]
