"""Mock handlers for ``toee_easyroutes_read`` (ports mock/easyroutes.ts, ADR-0063).

Both v1 actions are account-scoped: they require a Verified Customer and an order
reference owned by that customer (ADR-0043). Unmatched callers cannot call either
action, and a missing or non-owned order reference is a governed policy block,
never fabricated delivery facts (ADR-0020). Outputs are deterministic.

Handlers receive ``(params, context)`` faithfully to the TS source: the verified
customer identity is read from the Session Identity Snapshot at ``context.identity``
(ADR-0043), while the order reference stays a request ``param``. Data is injectable
so the Launch Eval fixture loader can override the baseline seeded from
``eval/mocks/base.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ...errors import ToolDriverError
from .driver import MockHandlerRegistry

if TYPE_CHECKING:
    from ...tool_gate import ToolExecutionContext


@dataclass(frozen=True)
class EasyroutesDelivery:
    order_number: str
    shopify_customer_id: str
    status: str
    stop_sequence: int
    eta_window: str
    route_name: str


@dataclass(frozen=True)
class EasyroutesMockData:
    deliveries: list[EasyroutesDelivery] = field(default_factory=list)


# Seeded from eval/mocks/base.yaml (easyroutes.deliveries.delivery_a). The
# delivery is tied to order 1042, which Shopify base data owns under
# gid://shopify/Customer/1001, so the delivery carries that owner link here.
easyroutes_baseline_data = EasyroutesMockData(
    deliveries=[
        EasyroutesDelivery(
            order_number="1042",
            shopify_customer_id="gid://shopify/Customer/1001",
            status="in_transit",
            stop_sequence=4,
            eta_window="2026-01-02T14:00:00Z/2026-01-02T16:00:00Z",
            route_name="Route 7 - GTA West",
        ),
    ],
)


def _read_string(params: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = params.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _require_verified_customer_id(context: "ToolExecutionContext") -> str:
    """Return the verified customer's id or raise a governed policy block.

    Ports ``requireVerifiedCustomerId``: only a Verified Customer may read
    EasyRoutes deliveries (ADR-0043). The identity comes from the Session
    Identity Snapshot at ``context.identity`` (``None`` for an Unmatched Caller).
    """
    identity = context.identity
    if identity is None or identity.get("outcome") != "verified_customer":
        raise ToolDriverError(
            "policy_blocked",
            "EasyRoutes read requires a verified customer.",
        )
    customer_id = identity.get("shopify_customer_id")
    if not isinstance(customer_id, str) or not customer_id:
        raise ToolDriverError(
            "policy_blocked",
            "EasyRoutes read requires a verified customer.",
        )
    return customer_id


def _find_owned_delivery(
    data: EasyroutesMockData, customer_id: str, order_number: str | None
) -> EasyroutesDelivery:
    """Resolve a delivery the verified customer owns.

    A missing or non-owned order reference is a governed policy block, never
    fabricated delivery facts (ports ``findOwnedDelivery``).
    """
    for candidate in data.deliveries:
        if (
            candidate.order_number == order_number
            and candidate.shopify_customer_id == customer_id
        ):
            return candidate
    raise ToolDriverError(
        "policy_blocked",
        f"No delivery for order {order_number or '<missing>'} "
        "owned by the verified customer.",
    )


def _get_delivery_status(
    data: EasyroutesMockData,
    params: dict[str, Any],
    context: "ToolExecutionContext",
) -> dict[str, Any]:
    customer_id = _require_verified_customer_id(context)
    delivery = _find_owned_delivery(
        data, customer_id, _read_string(params, "order_number", "orderNumber")
    )
    return {"order_number": delivery.order_number, "status": delivery.status}


def _get_route_details(
    data: EasyroutesMockData,
    params: dict[str, Any],
    context: "ToolExecutionContext",
) -> dict[str, Any]:
    customer_id = _require_verified_customer_id(context)
    delivery = _find_owned_delivery(
        data, customer_id, _read_string(params, "order_number", "orderNumber")
    )
    return {
        "order_number": delivery.order_number,
        "stop_sequence": delivery.stop_sequence,
        "eta_window": delivery.eta_window,
        "route_name": delivery.route_name,
    }


def create_easyroutes_mock_handlers(
    data: EasyroutesMockData = easyroutes_baseline_data,
) -> MockHandlerRegistry:
    """Build the registry fragment bound to a specific data set.

    The Launch Eval fixture loader passes per-scenario data; the default uses the
    base.yaml baseline.
    """
    return {
        "toee_easyroutes_read": {
            "get_delivery_status": lambda params, context: _get_delivery_status(
                data, params, context
            ),
            "get_route_details": lambda params, context: _get_route_details(
                data, params, context
            ),
        }
    }
