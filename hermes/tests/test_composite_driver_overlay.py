"""S04: per-tool driver overlay (``extra_drivers``) on the async external turn.

``register_turn`` threads an optional ``extra_drivers`` map through ``_register``
into :func:`_build_driver_selector`, so ``toee_customer_memory`` routes to the
injected datastore driver while every other tool keeps its mock/composio backing.
Selector precedence is ``extra_drivers[tool]`` -> composio (Layer 1) -> mock; the
governed dispatch (catalog check, Tool Gate, allowlist) runs before the driver, so
swapping it introduces no governance drift.

These run the real governed dispatch (:func:`execute_tool`) through a faithful
``RecordingCtx`` and observe which driver handled each tool.
"""

from __future__ import annotations

import json
from typing import Any

from toee_hermes import plugin
from toee_hermes.plugin import _build_driver_selector, register_turn
from toee_hermes.plugin.profiles import EXTERNAL


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
    """A ``ToolDriver`` recording dispatched tools and returning a kind-tagged echo."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.calls: list[str] = []

    def execute(self, request: Any, context: Any) -> Any:
        self.calls.append(request.tool)
        return {"routed_through": self.kind, "tool": request.tool}


def _handler(ctx: RecordingCtx, name: str) -> Any:
    return next(tool for tool in ctx.tools if tool["name"] == name)["handler"]


def test_register_turn_routes_the_override_tool_to_the_injected_driver(monkeypatch) -> None:
    monkeypatch.setenv("INTEGRATION_DRIVER", "mock")
    datastore = RecordingDriver("datastore")

    ctx = RecordingCtx(profile=EXTERNAL)
    register_turn(
        ctx,
        conversation_id="conv-A",
        extra_drivers={"toee_customer_memory": datastore},
    )

    # The overridden tool dispatches through the injected datastore driver.
    out = json.loads(
        _handler(ctx, "toee_customer_memory__upsert_preference")(
            {"key": "channel_preference", "value": "sms"}
        )
    )
    assert out == {"routed_through": "datastore", "tool": "toee_customer_memory"}
    assert datastore.calls == ["toee_customer_memory"]

    # Every other tool stays on the shared mock driver (real mock contract, not the fake).
    products = json.loads(
        _handler(ctx, "toee_shopify_read__search_products")({"query": "225"})
    )
    assert isinstance(products, list)
    assert datastore.calls == ["toee_customer_memory"]  # never routed a non-override tool


def test_selector_precedence_is_extra_then_composio_then_mock(monkeypatch) -> None:
    monkeypatch.setenv("INTEGRATION_DRIVER", "composio")
    composio = RecordingDriver("composio")
    monkeypatch.setattr(plugin, "build_composio_driver", lambda: composio)
    datastore = RecordingDriver("datastore")

    select = _build_driver_selector(None, {"toee_customer_memory": datastore})

    # extra_drivers wins for its tool, even under the composio backend...
    assert select("toee_customer_memory") is datastore
    # ...composio still backs its Layer-1 tools...
    assert select("toee_shopify_read") is composio
    # ...and every other tool stays on mock.
    assert select("toee_knowledge_search").kind == "mock"


def test_no_extra_drivers_leaves_every_tool_on_the_backend(monkeypatch) -> None:
    # Regression guard for the mock deployment (S05 owns full no-DB degradation):
    # without an override, customer memory stays on the shared mock driver.
    monkeypatch.setenv("INTEGRATION_DRIVER", "mock")
    select = _build_driver_selector(None)

    assert select("toee_customer_memory").kind == "mock"
    assert select("toee_shopify_read").kind == "mock"
