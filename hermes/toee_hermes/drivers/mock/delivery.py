"""Mock handlers for ``toee_delivery_promise`` (0.0.4 S31b).

Parity fixture for the live delivery-promise driver
(:mod:`toee_hermes.drivers.delivery.driver`): the SAME output contract, so local dev
and Launch Eval replay exercise one shape. Both actions are verified-customer scoped
(ADR-0043): an unverified/unmatched caller is a governed ``policy_blocked``, never
fabricated delivery facts (ADR-0020).

- ``get_order_delivery`` (Tier 2): the delivery block for an order the verified
  customer owns; a non-owned/unknown order fails closed ``not_found`` — mirroring the
  endpoint's 404 ownership enforcement (no leak).
- ``get_product_promise`` (Tier 3a): a per-variant promise for the verified customer.
  The seeded promise carries the endpoint's customer-safe prose (``displayLine`` /
  ``disclaimer``), including the cold-start ``address_missing`` state that is a REAL
  answer, not an error.

Data is injectable so the eval fixture loader can override the baseline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ...errors import ToolDriverError
from ..delivery.driver import _numeric_customer_id
from .driver import MockHandlerRegistry

if TYPE_CHECKING:
    from ...tool_gate import ToolExecutionContext


@dataclass(frozen=True)
class DeliveryOrderRecord:
    order_id: str
    order_name: str
    owner_numeric_id: str  # Shopify numeric customer id the endpoint compares
    delivery: dict[str, Any]


@dataclass(frozen=True)
class DeliveryMockData:
    orders: list[DeliveryOrderRecord] = field(default_factory=list)
    # sku -> variantId, the way the live endpoint resolves+validates a sku to a real
    # in-shop variant BEFORE the engine (unknown sku -> 404). The mock is keyed the same
    # so it is not more permissive than the endpoint (S30 parity lesson).
    variant_by_sku: dict[str, str] = field(
        default_factory=lambda: {"TRIM00014": "39379581042771"}
    )
    # The canned Tier 3a promise block echoed for a resolved variant (the mock does not
    # simulate the same-day engine; it proves relay parity).
    product_promise: dict[str, Any] = field(
        default_factory=lambda: dict(_BASELINE_PROMISE)
    )
    timezone: str = "America/Toronto"
    business_date: str = "2026-07-24"


# Seeded from the S31a live dev fixture (Si Li, customer 1019382595648, order
# 7189924970579 / OL49597). Numeric owner id matches what the endpoint compares.
_BASELINE_DELIVERY = {
    "status": "out_for_delivery",
    "statusHeadline": "Out for delivery today",
    "statusDetail": "On route Oakville Local #9813.",
    "deliveredAt": None,
    "routeLabel": "Oakville Local #9813",
    "estimatedReturnAt": "2026-07-24T21:00:00Z",
    "paymentMethodLabel": "Paid online",
    "pod": {"photoUrls": [], "note": None},
    "disclaimer": "Delivery times are estimates and may change.",
}

# Cold-start promise: a REAL success the endpoint answers with customer-safe prose.
_BASELINE_PROMISE = {
    "status": "address_missing",
    "deliveryTiming": None,
    "displayLine": "Add a delivery address to see when this arrives.",
    "disclaimer": "Delivery estimates need a shipping address on file.",
    "marketingCutoffLocal": None,
    "countdownSeconds": None,
    "orderByDeadline": None,
    "inventoryStatus": "in_stock",
    "servingWarehouseLabel": None,
    "serviceZoneLabel": None,
    "extraDayReason": None,
    "promiseWindow": None,
    "confidence": None,
    "learningPhase": "cold_start",
    "matchMode": None,
}

delivery_baseline_data = DeliveryMockData(
    orders=[
        DeliveryOrderRecord(
            order_id="7189924970579",
            order_name="OL49597",
            owner_numeric_id="1019382595648",
            delivery=dict(_BASELINE_DELIVERY),
        ),
    ],
)


def _read_string(params: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = params.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
    return None


def _require_verified_numeric_id(context: "ToolExecutionContext") -> str:
    identity = context.identity
    if not isinstance(identity, dict) or identity.get("outcome") != "verified_customer":
        raise ToolDriverError(
            "policy_blocked", "Delivery read requires a verified customer."
        )
    customer_id = identity.get("shopify_customer_id")
    if not isinstance(customer_id, str) or not customer_id:
        raise ToolDriverError(
            "policy_blocked", "Delivery read requires a verified customer."
        )
    return _numeric_customer_id(customer_id)


def _get_order_delivery(
    data: DeliveryMockData, params: dict[str, Any], context: "ToolExecutionContext"
) -> dict[str, Any]:
    numeric_id = _require_verified_numeric_id(context)
    # The endpoint resolves the order NAME (e.g. "OL49597") to the order within the shop
    # (numeric orderId still works too), then enforces ownership -> 404. The mock is keyed
    # the same way: match by name or numeric id, then check ownership.
    order_ref = _read_string(params, "order_name", "order_number", "orderName", "orderNumber", "order_id", "orderId")
    for record in data.orders:
        if order_ref in (record.order_name, record.order_id):
            if record.owner_numeric_id != numeric_id:
                raise ToolDriverError("not_found", "No order found for this customer.")
            return {
                "order_id": record.order_id,
                "order_name": record.order_name,
                "delivery": dict(record.delivery),
            }
    raise ToolDriverError("not_found", "No order found for this customer.")


def _get_product_promise(
    data: DeliveryMockData, params: dict[str, Any], context: "ToolExecutionContext"
) -> dict[str, Any]:
    _require_verified_numeric_id(context)
    # The endpoint resolves+validates a sku to a real in-shop variant before the engine
    # (unknown sku -> 404); a raw numeric variantId still works. Mirror that resolution.
    sku = _read_string(params, "sku")
    variant_id = _read_string(params, "variant_id", "variantId")
    if sku:
        resolved = data.variant_by_sku.get(sku)
        if resolved is None:
            raise ToolDriverError("not_found", "Unknown sku.")
        variant_id = resolved
    elif not variant_id:
        raise ToolDriverError("policy_blocked", "get_product_promise requires a sku.")
    quantity = params.get("quantity")
    quantity = quantity if isinstance(quantity, int) and not isinstance(quantity, bool) else None
    return {
        "variant_id": variant_id,
        "sku": sku,
        "quantity": quantity,
        "business_date": data.business_date,
        "timezone": data.timezone,
        "product_delivery_promise": dict(data.product_promise),
    }


def create_delivery_mock_handlers(
    data: DeliveryMockData = delivery_baseline_data,
) -> MockHandlerRegistry:
    """Build the registry fragment bound to a specific data set."""
    return {
        "toee_delivery_promise": {
            "get_order_delivery": lambda params, context: _get_order_delivery(
                data, params, context
            ),
            "get_product_promise": lambda params, context: _get_product_promise(
                data, params, context
            ),
        }
    }
