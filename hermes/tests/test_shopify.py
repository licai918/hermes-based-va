"""Mock handlers for toee_shopify_read (ports mock/shopify.test.ts, ADR-0061).

Order reads are account-scoped to a Verified Customer who owns the order; product
reads are public catalog (ADR-0032) and strip account-scoped price/inventory for
anyone who is not a Verified Customer. Every handler is exercised through
``execute_tool`` so the governed boundary is covered end-to-end.

The Session Identity Snapshot the handlers read (ADR-0043) is threaded through
``ToolExecutionContext.identity``: ``None`` for an unmatched caller, otherwise a
dict carrying ``outcome`` and, when verified, the owning ``shopify_customer_id``.
"""

from toee_hermes.drivers.mock.driver import MockDriver
from toee_hermes.drivers.mock.shopify import (
    ShopifyLineItem,
    ShopifyMockData,
    ShopifyOrder,
    create_shopify_mock_handlers,
    shopify_baseline_data,
)
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

VERIFIED_CUSTOMER_ID = "gid://shopify/Customer/1001"
OTHER_CUSTOMER_ID = "gid://shopify/Customer/9999"
BASELINE_PRODUCT_ID = "gid://shopify/Product/7001"


def _verified() -> dict:
    return {
        "outcome": "verified_customer",
        "shopify_customer_id": VERIFIED_CUSTOMER_ID,
        "company_name": "Acme Fleet",
    }


def _ambiguous() -> dict:
    return {
        "outcome": "ambiguous_phone_match",
        "shopify_customer_ids": [OTHER_CUSTOMER_ID, "gid://shopify/Customer/2002"],
    }


def _other_owner() -> dict:
    return {
        "outcome": "verified_customer",
        "shopify_customer_id": OTHER_CUSTOMER_ID,
        "company_name": "Other Co",
    }


def _driver(handlers=None) -> MockDriver:
    return MockDriver(handlers or create_shopify_mock_handlers())


def _ctx(identity=None) -> ToolExecutionContext:
    return ToolExecutionContext(profile="customer_service_external", identity=identity)


def _call(
    action: str,
    params: dict | None = None,
    *,
    identity=None,
    driver: MockDriver | None = None,
):
    return execute_tool(
        tool="toee_shopify_read",
        action=action,
        params=params or {},
        context=_ctx(identity),
        driver=driver or _driver(),
    )


# --- get_order: account-scoped to the verified owning customer ---------------


def test_get_order_returns_order_for_verified_owner() -> None:
    result = _call("get_order", {"order_number": "1042"}, identity=_verified())

    assert result.ok is True
    assert result.data["order_number"] == "1042"
    assert result.data["customer_id"] == VERIFIED_CUSTOMER_ID
    assert result.data["line_items"] == [
        {"sku": "TIRE-225-60R16", "title": "All-Season 225/60R16"}
    ]


def test_get_order_blocks_unmatched_caller() -> None:
    result = _call("get_order", {"order_number": "1042"}, identity=None)

    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_get_order_blocks_ambiguous_phone_match() -> None:
    result = _call("get_order", {"order_number": "1042"}, identity=_ambiguous())

    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_get_order_blocks_verified_customer_reading_unowned_order() -> None:
    result = _call("get_order", {"order_number": "1042"}, identity=_other_owner())

    assert result.ok is False
    assert result.error_class == "policy_blocked"


# --- list_customer_orders: only the verified customer's own orders -----------


def test_list_customer_orders_returns_only_owned_orders() -> None:
    result = _call("list_customer_orders", identity=_verified())

    assert result.ok is True
    assert result.data == [
        {
            "order_number": "1042",
            "customer_id": VERIFIED_CUSTOMER_ID,
            "line_items": [
                {"sku": "TIRE-225-60R16", "title": "All-Season 225/60R16"}
            ],
        }
    ]


def test_list_customer_orders_blocks_unmatched_caller() -> None:
    result = _call("list_customer_orders", identity=None)

    assert result.ok is False
    assert result.error_class == "policy_blocked"


# --- search_products: public catalog, never account-scoped fields ------------


def test_search_products_returns_public_fields_only_for_unmatched() -> None:
    result = _call("search_products", {"query": "225"}, identity=None)

    assert result.ok is True
    assert len(result.data) > 0
    for product in result.data:
        assert "price" not in product
        assert "inventory" not in product
        assert "product_url" in product
        assert "media_url" in product


def test_search_products_without_query_returns_all_public() -> None:
    result = _call("search_products")

    assert result.ok is True
    assert len(result.data) == len(shopify_baseline_data.products)
    for product in result.data:
        assert "price" not in product
        assert "inventory" not in product


def test_search_products_matches_by_sku() -> None:
    result = _call("search_products", {"query": "tire-225"})

    assert result.ok is True
    assert [product["product_id"] for product in result.data] == [BASELINE_PRODUCT_ID]


# --- get_product: public for non-verified, live facts for verified -----------


def test_get_product_unmatched_returns_public_only() -> None:
    result = _call("get_product", {"product_id": BASELINE_PRODUCT_ID}, identity=None)

    assert result.ok is True
    assert "price" not in result.data
    assert "inventory" not in result.data
    assert result.data["product_url"].startswith("https://")
    assert result.data["media_url"].startswith("https://")


def test_get_product_verified_includes_price_and_inventory() -> None:
    result = _call(
        "get_product", {"product_id": BASELINE_PRODUCT_ID}, identity=_verified()
    )

    assert result.ok is True
    assert result.data["price"] == "189.99"
    assert result.data["inventory"] == 24


def test_get_product_matches_by_sku() -> None:
    result = _call("get_product", {"sku": "TIRE-225-60R16"})

    assert result.ok is True
    assert result.data["product_id"] == BASELINE_PRODUCT_ID


def test_get_product_not_found_is_unexpected_error() -> None:
    result = _call(
        "get_product", {"product_id": "gid://shopify/Product/0000"}, identity=_verified()
    )

    assert result.ok is False
    assert result.error_class == "unexpected_error"


# --- data injection + determinism -------------------------------------------


def test_get_order_reads_data_injected_through_the_factory() -> None:
    handlers = create_shopify_mock_handlers(
        ShopifyMockData(
            orders=(
                ShopifyOrder(
                    order_number="2000",
                    customer_id=VERIFIED_CUSTOMER_ID,
                    line_items=(ShopifyLineItem(sku="TIRE-TEST", title="Injected Tire"),),
                ),
            ),
            products=(),
        )
    )

    result = _call(
        "get_order",
        {"order_number": "2000"},
        identity=_verified(),
        driver=_driver(handlers),
    )

    assert result.ok is True
    assert result.data["order_number"] == "2000"
    assert result.data["line_items"] == [{"sku": "TIRE-TEST", "title": "Injected Tire"}]


def test_outputs_are_deterministic_and_carry_no_timestamp() -> None:
    first = _call("get_order", {"order_number": "1042"}, identity=_verified())
    second = _call("get_order", {"order_number": "1042"}, identity=_verified())

    assert first.data == second.data
    assert "resolved_at" not in first.data
