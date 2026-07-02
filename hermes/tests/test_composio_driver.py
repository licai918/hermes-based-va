"""ComposioDriver Layer 1 mapping (ADR-0127/0128/0130/0136).

The Composio driver performs the backend call and reshapes the raw vendor payload
into the exact public ``toee_*`` contract the mock drivers produce. Gating runs in
``execute_tool`` BEFORE the driver, so these tests drive ``ComposioDriver.execute``
directly with a fake ``ComposioClient`` (no network) and assert:

- the strict one-to-one action mapping (each action calls exactly one Composio
  slug from ``ACTION_MAPPING`` with the toolkit's ``connected_account_id`` + ``user_id``),
- byte-identical response shapes vs. the mock contracts,
- a client exception becomes a governed ``ToolDriverError`` (no raw vendor leak),
- a non-Layer-1 / unmapped tool raises ``ToolDriverError("configuration_missing")``.
"""

from __future__ import annotations

from typing import Any

import pytest

from toee_hermes.drivers.composio import ACTION_MAPPING, ComposioDriver
from toee_hermes.errors import ToolDriverError
from toee_hermes.execute import ToolRequest
from toee_hermes.tool_gate import ToolExecutionContext

VERIFIED_CUSTOMER_ID = "gid://shopify/Customer/1001"
CONVERSATION_ID = "textline:conv_abc123"
USER_ID = "toee-staging"
CONNECTED_ACCOUNTS = {"shopify": "ca_shopify", "qbo": "ca_qbo", "square": "ca_square"}


class FakeComposioClient:
    """Records each backend call and returns a canned raw vendor payload."""

    def __init__(self, response: Any = None, *, error: Exception | None = None) -> None:
        self._response = {} if response is None else response
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def execute_action(
        self,
        *,
        action: str,
        params: dict[str, Any],
        connected_account_id: str | None,
        user_id: str | None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "action": action,
                "params": params,
                "connected_account_id": connected_account_id,
                "user_id": user_id,
            }
        )
        if self._error is not None:
            raise self._error
        return self._response


def _driver(client: FakeComposioClient) -> ComposioDriver:
    return ComposioDriver(
        client, user_id=USER_ID, connected_accounts=CONNECTED_ACCOUNTS
    )


def _ctx(*, identity: Any = None, conversation_id: str | None = None) -> ToolExecutionContext:
    return ToolExecutionContext(
        profile="customer_service_external",
        identity=identity,
        conversation_id=conversation_id,
    )


def _verified() -> dict[str, Any]:
    return {"outcome": "verified_customer", "shopify_customer_id": VERIFIED_CUSTOMER_ID}


def _run(
    client: FakeComposioClient,
    tool: str,
    action: str,
    params: dict[str, Any],
    context: ToolExecutionContext,
) -> Any:
    return _driver(client).execute(
        ToolRequest(tool=tool, action=action, params=params), context
    )


def _assert_one_to_one(
    client: FakeComposioClient, tool: str, action: str, expected_account: str
) -> None:
    """The action invoked exactly one Composio slug from the table for its toolkit."""
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["action"] == ACTION_MAPPING[(tool, action)].action_slug
    assert call["connected_account_id"] == expected_account
    assert call["user_id"] == USER_ID


# --- shopify -----------------------------------------------------------------


def test_shopify_get_order_maps_to_contract_shape() -> None:
    raw = {
        "order": {
            "order_number": "1042",
            "customer_id": VERIFIED_CUSTOMER_ID,
            "line_items": [
                {"sku": "TIRE-225-60R16", "title": "All-Season 225/60R16", "quantity": 2}
            ],
        }
    }
    client = FakeComposioClient(raw)
    out = _run(
        client,
        "toee_shopify_read",
        "get_order",
        {"order_number": "1042"},
        _ctx(identity=_verified()),
    )
    assert out == {
        "order_number": "1042",
        "customer_id": VERIFIED_CUSTOMER_ID,
        "line_items": [{"sku": "TIRE-225-60R16", "title": "All-Season 225/60R16"}],
    }
    _assert_one_to_one(client, "toee_shopify_read", "get_order", "ca_shopify")


def test_shopify_list_customer_orders_maps_each_item() -> None:
    raw = {
        "orders": [
            {
                "order_number": "1042",
                "customer_id": VERIFIED_CUSTOMER_ID,
                "line_items": [{"sku": "TIRE-225-60R16", "title": "All-Season 225/60R16"}],
            }
        ]
    }
    client = FakeComposioClient(raw)
    out = _run(
        client,
        "toee_shopify_read",
        "list_customer_orders",
        {},
        _ctx(identity=_verified()),
    )
    assert out == [
        {
            "order_number": "1042",
            "customer_id": VERIFIED_CUSTOMER_ID,
            "line_items": [{"sku": "TIRE-225-60R16", "title": "All-Season 225/60R16"}],
        }
    ]
    _assert_one_to_one(client, "toee_shopify_read", "list_customer_orders", "ca_shopify")


def test_shopify_list_customer_orders_strips_graphql_customer_id() -> None:
    client = FakeComposioClient({"orders": []})
    _run(
        client,
        "toee_shopify_read",
        "list_customer_orders",
        {},
        _ctx(identity=_verified()),
    )
    assert client.calls[0]["params"] == {"customer_id": "1001", "status": "any"}


def test_shopify_get_order_maps_nested_shopify_customer() -> None:
    raw = {
        "order": {
            "order_number": 49299,
            "customer": {"id": 6764623954003},
            "line_items": [{"sku": "SKU1", "title": "Tire"}],
        }
    }
    client = FakeComposioClient(raw)
    out = _run(
        client,
        "toee_shopify_read",
        "get_order",
        {"order_number": "7157788934227"},
        _ctx(identity=_verified()),
    )
    assert out == {
        "order_number": "49299",
        "customer_id": "gid://shopify/Customer/6764623954003",
        "line_items": [{"sku": "SKU1", "title": "Tire"}],
    }


def test_shopify_search_products_returns_public_fields_only() -> None:
    raw = {
        "products": [
            {
                "product_id": "gid://shopify/Product/7001",
                "sku": "TIRE-225-60R16",
                "title": "All-Season 225/60R16",
                "product_url": "https://shop.toee.example/products/all-season-225-60r16",
                "media_url": "https://cdn.toee.example/products/all-season-225-60r16.jpg",
                "price": "189.99",
                "inventory": 24,
            }
        ]
    }
    client = FakeComposioClient(raw)
    out = _run(
        client, "toee_shopify_read", "search_products", {"query": "225"}, _ctx()
    )
    assert out == [
        {
            "product_id": "gid://shopify/Product/7001",
            "sku": "TIRE-225-60R16",
            "title": "All-Season 225/60R16",
            "product_url": "https://shop.toee.example/products/all-season-225-60r16",
            "media_url": "https://cdn.toee.example/products/all-season-225-60r16.jpg",
        }
    ]
    for product in out:
        assert "price" not in product
        assert "inventory" not in product
    _assert_one_to_one(client, "toee_shopify_read", "search_products", "ca_shopify")


def _product_raw() -> dict[str, Any]:
    return {
        "product": {
            "product_id": "gid://shopify/Product/7001",
            "sku": "TIRE-225-60R16",
            "title": "All-Season 225/60R16",
            "product_url": "https://shop.toee.example/products/all-season-225-60r16",
            "media_url": "https://cdn.toee.example/products/all-season-225-60r16.jpg",
            "price": "189.99",
            "inventory": 24,
        }
    }


def test_shopify_get_product_public_for_non_verified() -> None:
    client = FakeComposioClient(_product_raw())
    out = _run(
        client,
        "toee_shopify_read",
        "get_product",
        {"product_id": "gid://shopify/Product/7001"},
        _ctx(identity=None),
    )
    assert out == {
        "product_id": "gid://shopify/Product/7001",
        "sku": "TIRE-225-60R16",
        "title": "All-Season 225/60R16",
        "product_url": "https://shop.toee.example/products/all-season-225-60r16",
        "media_url": "https://cdn.toee.example/products/all-season-225-60r16.jpg",
    }
    assert "price" not in out
    assert "inventory" not in out
    _assert_one_to_one(client, "toee_shopify_read", "get_product", "ca_shopify")


def test_shopify_get_product_includes_price_inventory_for_verified() -> None:
    client = FakeComposioClient(_product_raw())
    out = _run(
        client,
        "toee_shopify_read",
        "get_product",
        {"product_id": "gid://shopify/Product/7001"},
        _ctx(identity=_verified()),
    )
    assert out["price"] == "189.99"
    assert out["inventory"] == 24
    assert out["product_id"] == "gid://shopify/Product/7001"


# --- qbo ---------------------------------------------------------------------


def test_qbo_get_invoice_maps_to_contract_shape() -> None:
    raw = {
        "invoice": {
            "invoice_number": "INV-9001",
            "shopify_customer_id": VERIFIED_CUSTOMER_ID,
            "customer_email": "accounts@acme-fleet.example",
            "balance": 1250.0,
            "currency": "USD",
        }
    }
    client = FakeComposioClient(raw)
    out = _run(
        client,
        "toee_qbo_read",
        "get_invoice",
        {"invoice_number": "INV-9001"},
        _ctx(identity=_verified()),
    )
    assert out == {
        "invoice_number": "INV-9001",
        "shopify_customer_id": VERIFIED_CUSTOMER_ID,
        "customer_email": "accounts@acme-fleet.example",
        "balance": 1250.0,
    }
    _assert_one_to_one(client, "toee_qbo_read", "get_invoice", "ca_qbo")


def test_qbo_list_customer_invoices_maps_each_item() -> None:
    raw = {
        "invoices": [
            {
                "invoice_number": "INV-9001",
                "shopify_customer_id": VERIFIED_CUSTOMER_ID,
                "customer_email": "accounts@acme-fleet.example",
                "balance": 1250.0,
            }
        ]
    }
    client = FakeComposioClient(raw)
    out = _run(
        client, "toee_qbo_read", "list_customer_invoices", {}, _ctx(identity=_verified())
    )
    assert out == [
        {
            "invoice_number": "INV-9001",
            "shopify_customer_id": VERIFIED_CUSTOMER_ID,
            "customer_email": "accounts@acme-fleet.example",
            "balance": 1250.0,
        }
    ]
    _assert_one_to_one(client, "toee_qbo_read", "list_customer_invoices", "ca_qbo")


def test_qbo_get_ar_summary_maps_to_contract_shape() -> None:
    raw = {
        "shopify_customer_id": VERIFIED_CUSTOMER_ID,
        "open_invoice_count": 1,
        "total_balance": 1250.0,
    }
    client = FakeComposioClient(raw)
    out = _run(
        client, "toee_qbo_read", "get_ar_summary", {}, _ctx(identity=_verified())
    )
    assert out == {
        "shopify_customer_id": VERIFIED_CUSTOMER_ID,
        "open_invoice_count": 1,
        "total_balance": 1250.0,
    }
    _assert_one_to_one(client, "toee_qbo_read", "get_ar_summary", "ca_qbo")


def test_qbo_get_ar_summary_parses_aged_receivables_report() -> None:
    raw = {
        "Rows": {
            "Row": [
                {
                    "ColData": [
                        {"value": "Acme Fleet"},
                        {"value": ""},
                        {"value": ""},
                        {"value": ""},
                        {"value": ""},
                        {"value": ""},
                        {"value": "125.50"},
                    ]
                },
                {
                    "type": "Section",
                    "group": "GrandTotal",
                    "Summary": {
                        "ColData": [
                            {"value": "TOTAL"},
                            {"value": "8337.09"},
                            {"value": "34332.85"},
                            {"value": "-5748.30"},
                            {"value": "-747.56"},
                            {"value": "-15220.96"},
                            {"value": "20953.12"},
                        ]
                    },
                },
            ]
        }
    }
    client = FakeComposioClient(raw)
    out = _run(
        client, "toee_qbo_read", "get_ar_summary", {}, _ctx(identity=_verified())
    )
    assert out == {
        "shopify_customer_id": VERIFIED_CUSTOMER_ID,
        "open_invoice_count": 1,
        "total_balance": 20953.12,
    }


# --- square ------------------------------------------------------------------


def test_square_send_payment_link_maps_to_contract_shape() -> None:
    raw = {"payment_link": {"url": "https://pay.toee.example/square/INV-9001", "amount": 1250.0}}
    client = FakeComposioClient(raw)
    out = _run(
        client,
        "toee_square_payment_link",
        "send_payment_link",
        {"invoice_number": "INV-9001"},
        _ctx(identity=_verified(), conversation_id=CONVERSATION_ID),
    )
    assert out == {
        "payment_link_url": "https://pay.toee.example/square/INV-9001",
        "conversation_id": CONVERSATION_ID,
        "amount": 1250.0,
    }
    _assert_one_to_one(
        client, "toee_square_payment_link", "send_payment_link", "ca_square"
    )


# --- governed failure + unsupported tool -------------------------------------


def test_client_exception_becomes_governed_tool_driver_error() -> None:
    client = FakeComposioClient(error=RuntimeError("composio 503: upstream boom"))
    with pytest.raises(ToolDriverError) as excinfo:
        _run(
            client,
            "toee_shopify_read",
            "get_order",
            {"order_number": "1042"},
            _ctx(identity=_verified()),
        )
    # A governed class is set, and the raw vendor message is not the customer reply.
    assert excinfo.value.error_class in {
        "composio_api_error",
        "vendor_timeout",
        "auth_expired",
        "unexpected_error",
    }


def test_client_raised_tool_driver_error_is_passed_through() -> None:
    client = FakeComposioClient(error=ToolDriverError("auth_expired", "token dead"))
    with pytest.raises(ToolDriverError) as excinfo:
        _run(
            client,
            "toee_qbo_read",
            "get_invoice",
            {"invoice_number": "INV-9001"},
            _ctx(identity=_verified()),
        )
    assert excinfo.value.error_class == "auth_expired"


def test_unsupported_non_layer1_tool_is_configuration_missing() -> None:
    client = FakeComposioClient({})
    with pytest.raises(ToolDriverError) as excinfo:
        _run(client, "toee_case", "create_case", {}, _ctx(identity=_verified()))
    assert excinfo.value.error_class == "configuration_missing"
    # Never reached the backend.
    assert client.calls == []


def test_missing_connected_account_is_configuration_missing() -> None:
    client = FakeComposioClient({"order": {}})
    driver = ComposioDriver(client, user_id=USER_ID, connected_accounts={})
    with pytest.raises(ToolDriverError) as excinfo:
        driver.execute(
            ToolRequest(tool="toee_shopify_read", action="get_order", params={}),
            _ctx(identity=_verified()),
        )
    assert excinfo.value.error_class == "configuration_missing"
    assert client.calls == []


def test_action_mapping_covers_exactly_the_layer1_actions() -> None:
    from toee_hermes.tool_catalog import TOOL_CATALOG
    from toee_hermes.drivers.composio import COMPOSIO_LAYER1_TOOLS

    expected = {
        (tool, action)
        for tool in COMPOSIO_LAYER1_TOOLS
        for action in TOOL_CATALOG[tool]
    }
    assert set(ACTION_MAPPING) == expected
    # Slugs are non-empty placeholders (exact values verified at staging smoke).
    for spec in ACTION_MAPPING.values():
        assert spec.action_slug
        assert spec.app in {"shopify", "qbo", "square"}
