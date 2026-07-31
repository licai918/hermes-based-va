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
from ...lexicon_seam import (
    LexiconVocabulary,
    current_lexicon_vocabulary,
    filter_products,
    is_canonical_size,
    product_matches,
    resolve_product_query,
)
from .driver import MockHandlerRegistry

if TYPE_CHECKING:
    from ...tool_gate import ToolExecutionContext


@dataclass(frozen=True)
class ShopifyLineItem:
    sku: str
    title: str


@dataclass(frozen=True)
class ShopifyTracking:
    number: str | None = None
    url: str | None = None
    company: str | None = None


@dataclass(frozen=True)
class ShopifyFulfillment:
    # Customer-facing delivery state (S30): unfulfilled / in_transit /
    # out_for_delivery / attempted_delivery / delivered / ready_for_pickup /
    # fulfilled. Mirrors the composio driver's projected fulfillment block.
    state: str
    shipment_status: str | None = None
    tracking: ShopifyTracking | None = None


@dataclass(frozen=True)
class ShopifyOrder:
    order_number: str
    customer_id: str
    line_items: tuple[ShopifyLineItem, ...] = ()
    fulfillment: ShopifyFulfillment | None = None


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
            # Order 1042 is out on an EasyRoutes route (matches easyroutes delivery_a
            # in_transit); the tracking url is the customer-clickable live page (FR-20).
            fulfillment=ShopifyFulfillment(
                state="in_transit",
                shipment_status="in_transit",
                tracking=ShopifyTracking(
                    number="ER-1042",
                    url="https://api.easyroutes.app/orders/status/route-7-stop-4",
                    company="EasyRoutes",
                ),
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


def _serialize_fulfillment(fulfillment: ShopifyFulfillment | None) -> dict[str, Any]:
    """Same block the composio driver projects (parity). None -> honest unfulfilled."""
    if fulfillment is None:
        return {"state": "unfulfilled", "shipment_status": None, "tracking": None}
    tracking = None
    if fulfillment.tracking is not None:
        tracking = {
            "number": fulfillment.tracking.number,
            "url": fulfillment.tracking.url,
            "company": fulfillment.tracking.company,
        }
    return {
        "state": fulfillment.state,
        "shipment_status": fulfillment.shipment_status,
        "tracking": tracking,
    }


def _serialize_order(order: ShopifyOrder) -> dict[str, Any]:
    return {
        "order_number": order.order_number,
        "customer_id": order.customer_id,
        "line_items": [
            {"sku": item.sku, "title": item.title} for item in order.line_items
        ],
        "fulfillment": _serialize_fulfillment(order.fulfillment),
    }


def _to_public_product(product: ShopifyProduct) -> dict[str, Any]:
    return {
        "product_id": product.product_id,
        "sku": product.sku,
        "title": product.title,
        "product_url": product.product_url,
        "media_url": product.media_url,
        # S31b: expose the variant sku(s) so the agent can pick the customer's size and
        # feed its sku to Tier 3a get_product_promise. Same [{sku, option}] shape the
        # composio driver projects (parity). ponytail: one product == one size here, so
        # a single derived variant; seed multiple products (or add a variants field) when
        # a scenario needs multi-size disambiguation under one product.
        "variants": [{"sku": product.sku, "option": product.title}],
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


def _search_catalog(
    data: ShopifyMockData, params: dict[str, Any]
) -> list[dict[str, Any]]:
    """One catalog read for one parameter set. The seam's ``lookup``.

    The matcher is :func:`~toee_hermes.lexicon_seam.product_matches` -- shared
    with the live twin, so "which products does this term reach" cannot mean two
    different things in the two drivers (NFR-7).
    """
    return filter_products(
        _read_string(params, "query"),
        (_to_public_product(product) for product in data.products),
    )


def _search_products(
    data: ShopifyMockData,
    params: dict[str, Any],
    vocabulary: LexiconVocabulary | None,
) -> list[dict[str, Any]]:
    # 0.0.5 S05 call site 1 of 2 in this twin (FR-5).
    return resolve_product_query(
        "search_products",
        params,
        lookup=lambda resolved: _search_catalog(data, resolved),
        vocabulary=vocabulary,
    ).value


def _find_product(
    data: ShopifyMockData, params: dict[str, Any]
) -> ShopifyProduct | None:
    """An EXACT id/sku lookup, with one narrow fallback for a normalized size.

    The exact pass runs over the WHOLE catalog first. Anything else lets catalog
    order decide the answer: a substring hit on an earlier product's title would
    outrank the exact sku match on a later one, and ``get_product`` would return a
    different product than the one it was asked for.

    The fallback exists because a normalized sku (``205/55R16``) is a size, not a
    stock code, so it has to be matched the way search matches or the seam could
    only ever hurt this action. It is gated on the value BEING a canonical size,
    which is the only thing the seam can hand this handler -- so with no
    vocabulary installed (eval, replay, every mock deployment) this stays the
    exact lookup it has always been (NFR-4).
    """
    product_id = _read_string(params, "product_id", "productId")
    sku = _read_string(params, "sku")
    exact = next(
        (
            candidate
            for candidate in data.products
            if (product_id is not None and candidate.product_id == product_id)
            or (sku is not None and candidate.sku == sku)
        ),
        None,
    )
    if exact is not None or not is_canonical_size(sku):
        return exact
    return next(
        (
            candidate
            for candidate in data.products
            if product_matches(sku, _to_public_product(candidate))
        ),
        None,
    )


def _get_product(
    data: ShopifyMockData,
    params: dict[str, Any],
    context: ToolExecutionContext,
    vocabulary: LexiconVocabulary | None,
) -> dict[str, Any]:
    # 0.0.5 S05 call site 2 of 2 in this twin (FR-5).
    product = resolve_product_query(
        "get_product",
        params,
        lookup=lambda resolved: _find_product(data, resolved),
        vocabulary=vocabulary,
    ).value
    if product is None:
        reference = _read_string(params, "product_id", "productId") or _read_string(
            params, "sku"
        )
        raise ToolDriverError(
            "unexpected_error",
            f"Product {reference or '<missing>'} not found.",
        )
    return (
        _to_verified_product(product)
        if _is_verified(context)
        else _to_public_product(product)
    )


def create_shopify_mock_handlers(
    data: ShopifyMockData = shopify_baseline_data,
    *,
    vocabulary: LexiconVocabulary | None = None,
) -> MockHandlerRegistry:
    """Build the registry fragment bound to a specific data set.

    The Launch Eval fixture loader passes per-scenario data; the default uses the
    base.yaml baseline. Each handler takes ``(params, context)``; only the
    account-domain reads consult ``context.identity`` (search stays public).

    ``vocabulary`` (0.0.5 S05) overrides the process-installed L7 vocabulary for
    the two product reads. Test seam only: a deployment installs ONE vocabulary
    (``install_lexicon_vocabulary``) so both twins read the same store, and every
    caller that passes nothing -- the eval harness included -- gets the installed
    one, which on the eval/replay path is deliberately absent.
    """

    def _vocabulary() -> LexiconVocabulary | None:
        return vocabulary if vocabulary is not None else current_lexicon_vocabulary()

    return {
        "toee_shopify_read": {
            "get_order": lambda params, context: _get_order(data, params, context),
            "list_customer_orders": lambda params, context: _list_customer_orders(
                data, context
            ),
            "search_products": lambda params, context: _search_products(
                data, params, _vocabulary()
            ),
            "get_product": lambda params, context: _get_product(
                data, params, context, _vocabulary()
            ),
        }
    }
