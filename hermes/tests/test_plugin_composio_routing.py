"""Per-tool driver routing for INTEGRATION_DRIVER=composio (ADR-0128/0137).

``mock`` stays the DEFAULT. When ``INTEGRATION_DRIVER=composio``, only the three
Layer-1 tools dispatch through the Composio driver; every other tool stays on the
mock driver, so each audit record's ``driver.kind`` is accurate per tool. The eval
recording path (``register_eval``) still routes ALL tools through its injected
driver and must never build the Composio driver.

These run the real governed dispatch (:func:`execute_tool`) through a faithful
``RecordingCtx`` and observe which driver handled each tool.
"""

from __future__ import annotations

import json
from typing import Any

from toee_hermes import plugin
from toee_hermes.plugin import register, register_eval
from toee_hermes.plugin.profiles import EXTERNAL
from toee_hermes.tool_gate import allow_all_gate


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
    """A ``ToolDriver`` that records dispatched tools and returns a kind-tagged echo."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.calls: list[str] = []

    def execute(self, request: Any, context: Any) -> Any:
        self.calls.append(request.tool)
        return {"routed_through": self.kind, "tool": request.tool}


def _handler(ctx: RecordingCtx, name: str) -> Any:
    return next(tool for tool in ctx.tools if tool["name"] == name)["handler"]


def _boom() -> Any:
    raise AssertionError("build_composio_driver must not be called on this path")


def test_mock_is_the_default_for_layer1_tools(monkeypatch) -> None:
    monkeypatch.delenv("INTEGRATION_DRIVER", raising=False)
    # The default path must never reach for the Composio builder.
    monkeypatch.setattr(plugin, "build_composio_driver", _boom)

    ctx = RecordingCtx(profile=EXTERNAL)
    register(ctx)

    out = json.loads(
        _handler(ctx, "toee_shopify_read__search_products")({"query": "225"})
    )
    # Mock returns the real public-product list contract, not a composio sentinel.
    assert isinstance(out, list)
    assert all("routed_through" not in product for product in out)


def test_composio_routes_only_layer1_tools(monkeypatch) -> None:
    monkeypatch.setenv("INTEGRATION_DRIVER", "composio")
    composio = RecordingDriver("composio")
    monkeypatch.setattr(plugin, "build_composio_driver", lambda: composio)

    ctx = RecordingCtx(profile=EXTERNAL)
    register(ctx)

    # Layer-1 tool dispatches through the Composio driver.
    layer1 = json.loads(
        _handler(ctx, "toee_shopify_read__search_products")({"query": "tire"})
    )
    assert layer1 == {"routed_through": "composio", "tool": "toee_shopify_read"}
    assert composio.calls == ["toee_shopify_read"]

    # Non-Layer-1 tool stays on the mock driver (never recorded by the composio fake).
    knowledge = json.loads(
        _handler(ctx, "toee_knowledge_search__search_public_site")({"query": "warranty"})
    )
    assert "results" in knowledge
    assert "routed_through" not in knowledge
    assert composio.calls == ["toee_shopify_read"]


def test_all_three_layer1_tools_route_to_composio(monkeypatch) -> None:
    monkeypatch.setenv("INTEGRATION_DRIVER", "composio")
    composio = RecordingDriver("composio")
    monkeypatch.setattr(plugin, "build_composio_driver", lambda: composio)

    ctx = RecordingCtx(profile=EXTERNAL)
    register(ctx)

    _handler(ctx, "toee_shopify_read__get_order")({"order_number": "1042"})
    _handler(ctx, "toee_qbo_read__get_invoice")({"invoice_number": "INV-9001"})
    _handler(ctx, "toee_square_payment_link__send_payment_link")({"invoice_number": "INV-9001"})

    assert set(composio.calls) == {
        "toee_shopify_read",
        "toee_qbo_read",
        "toee_square_payment_link",
    }


def test_register_eval_overrides_all_tools_even_when_composio_selected(monkeypatch) -> None:
    monkeypatch.setenv("INTEGRATION_DRIVER", "composio")
    # The eval path injects its own driver and must NOT build the Composio driver.
    monkeypatch.setattr(plugin, "build_composio_driver", _boom)
    eval_driver = RecordingDriver("mock")

    ctx = RecordingCtx(profile=EXTERNAL)
    register_eval(ctx, driver=eval_driver, gate=allow_all_gate, identity=None)

    # Even a Layer-1 tool routes through the injected eval driver.
    out = json.loads(
        _handler(ctx, "toee_shopify_read__get_order")({"order_number": "1042"})
    )
    assert out == {"routed_through": "mock", "tool": "toee_shopify_read"}
    assert eval_driver.calls == ["toee_shopify_read"]
