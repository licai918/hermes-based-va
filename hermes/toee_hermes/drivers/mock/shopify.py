"""Mock handlers for ``toee_shopify_read`` (ports mock/shopify.ts, ADR-0061).

Order reads are account-scoped and require a Verified Customer who owns the
order; product reads are public catalog (ADR-0032) and strip account-scoped
price/inventory for anyone who is not a Verified Customer. Outputs are
deterministic — no clocks or randomness. Data is injectable so the Launch Eval
fixture loader can override the baseline seeded from ``eval/mocks/base.yaml``.

Handlers receive ``(params, context)`` (faithful to the TS handlers). The Session
Identity Snapshot lives at ``context.identity`` (ADR-0043): ``None`` for an
unmatched caller, otherwise a dict carrying ``outcome`` and, when verified, the
owning ``shopify_customer_id``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ...errors import ToolDriverError
from .driver import MockHandlerRegistry

if TYPE_CHECKING:
    from ...tool_gate import ToolExecutionContext


@dataclass(frozen=True)
class ShopifyLineItem:
    sku: str
    title: str


@dataclass(frozen=True)
class ShopifyOrder:
    order_number: str
    customer_id: str
    line_items: tuple[ShopifyLineItem, ...] = ()


@dataclass(frozen=True)
class ShopifyProduct:
    product_id: str
    sku: str
    title: str
    # Public catalog fields, safe for any caller.
    product_url: str
    media_url: str
    # Account-scoped live facts, only disclosed to Verified Customers.
    price: str | None = None
    inventory: int | None = None


@dataclass(frozen=True)
class ShopifyMockData:
    orders: tuple[ShopifyOrder, ...] = ()
    products: tuple[ShopifyProduct, ...] = ()


# Seeded from eval/mocks/base.yaml (shopify.orders.recent_order_a). The product
# catalog has no base.yaml slice, so one deterministic product is seeded to back
# search_products / get_product, aligned to the order's line item SKU.
shopify_baseline_data = ShopifyMockData(
    orders=(
        ShopifyOrder(
            order_number="1042",
            customer_id="gid://shopify/Customer/1001",
            line_items=(
                ShopifyLineItem(sku="TIRE-225-60R16", title="All-Season 225/60R16"),
            ),
        ),
    ),
    products=(
        ShopifyProduct(
            product_id="gid://shopify/Product/7001",
            sku="TIRE-225-60R16",
            title="All-Season 225/60R16",
            product_url="https://shop.toee.example/products/all-season-225-60r16",
            media_url="https://cdn.toee.example/products/all-season-225-60r16.jpg",
            price="189.99",
            inventory=24,
        ),
    ),
)


def _read_string(params: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = params.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _identity(context: ToolExecutionContext) -> dict[str, Any] | None:
    identity = context.identity
    return identity if isinstance(identity, dict) else None


def _is_verified(context: ToolExecutionContext) -> bool:
    identity = _identity(context)
    return identity is not None and identity.get("outcome") == "verified_customer"


def _require_verified_customer_id(context: ToolExecutionContext) -> str:
    """Account-scoped Shopify reads require a Verified Customer (ADR-0061).

    Unmatched and ambiguous sessions never receive order facts.
    """
    identity = _identity(context)
    if identity is None or identity.get("outcome") != "verified_customer":
        raise ToolDriverError(
            "policy_blocked",
            "Account-scoped Shopify read requires a verified customer.",
        )
    customer_id = identity.get("shopify_customer_id")
    if not isinstance(customer_id, str) or not customer_id:
        raise ToolDriverError(
            "policy_blocked",
            "Verified customer session is missing a Shopify customer id.",
        )
    return customer_id


def _serialize_order(order: ShopifyOrder) -> dict[str, Any]:
    return {
        "order_number": order.order_number,
        "customer_id": order.customer_id,
        "line_items": [
            {"sku": item.sku, "title": item.title} for item in order.line_items
        ],
    }


def _to_public_product(product: ShopifyProduct) -> dict[str, Any]:
    return {
        "product_id": product.product_id,
        "sku": product.sku,
        "title": product.title,
        "product_url": product.product_url,
        "media_url": product.media_url,
    }


def _to_verified_product(product: ShopifyProduct) -> dict[str, Any]:
    return {
        **_to_public_product(product),
        "price": product.price,
        "inventory": product.inventory,
    }


def _get_order(
    data: ShopifyMockData, params: dict[str, Any], context: ToolExecutionContext
) -> dict[str, Any]:
    customer_id = _require_verified_customer_id(context)
    order_number = _read_string(params, "order_number", "orderNumber")
    for order in data.orders:
        if order.order_number == order_number and order.customer_id == customer_id:
            return _serialize_order(order)
    raise ToolDriverError(
        "policy_blocked",
        f"No order {order_number or '<missing>'} owned by the verified customer.",
    )


def _list_customer_orders(
    data: ShopifyMockData, context: ToolExecutionContext
) -> list[dict[str, Any]]:
    customer_id = _require_verified_customer_id(context)
    return [
        _serialize_order(order)
        for order in data.orders
        if order.customer_id == customer_id
    ]


def _search_products(
    data: ShopifyMockData, params: dict[str, Any]
) -> list[dict[str, Any]]:
    query = _read_string(params, "query")
    if query is None:
        matches = list(data.products)
    else:
        needle = query.lower()
        matches = [
            product
            for product in data.products
            if needle in product.title.lower() or needle in product.sku.lower()
        ]
    return [_to_public_product(product) for product in matches]


def _get_product(
    data: ShopifyMockData, params: dict[str, Any], context: ToolExecutionContext
) -> dict[str, Any]:
    product_id = _read_string(params, "product_id", "productId")
    sku = _read_string(params, "sku")
    product = next(
        (
            candidate
            for candidate in data.products
            if candidate.product_id == product_id or candidate.sku == sku
        ),
        None,
    )
    if product is None:
        raise ToolDriverError(
            "unexpected_error",
            f"Product {product_id or sku or '<missing>'} not found.",
        )
    return (
        _to_verified_product(product)
        if _is_verified(context)
        else _to_public_product(product)
    )


def create_shopify_mock_handlers(
    data: ShopifyMockData = shopify_baseline_data,
) -> MockHandlerRegistry:
    """Build the registry fragment bound to a specific data set.

    The Launch Eval fixture loader passes per-scenario data; the default uses the
    base.yaml baseline. Each handler takes ``(params, context)``; only the
    account-domain reads consult ``context.identity`` (search stays public).
    """
    return {
        "toee_shopify_read": {
            "get_order": lambda params, context: _get_order(data, params, context),
            "list_customer_orders": lambda params, context: _list_customer_orders(
                data, context
            ),
            "search_products": lambda params, context: _search_products(data, params),
            "get_product": lambda params, context: _get_product(data, params, context),
        }
    }
