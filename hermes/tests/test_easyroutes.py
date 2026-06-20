"""toee_easyroutes_read mock handlers (ports mock/easyroutes.test.ts, ADR-0063).

Both actions are account-scoped: they require a Verified Customer and an order
reference owned by that customer (ADR-0043). Unmatched callers and non-owners are
governed policy blocks, never fabricated delivery facts (ADR-0020).

The verified customer identity is supplied through the Session Identity Snapshot
at ``context.identity`` (``None`` for an Unmatched Caller); the order reference is
a request ``param``. Every handler is exercised end-to-end through ``execute_tool``
so the governed boundary is covered.
"""

from toee_hermes.drivers.mock.driver import MockDriver
from toee_hermes.drivers.mock.easyroutes import (
    EasyroutesDelivery,
    EasyroutesMockData,
    create_easyroutes_mock_handlers,
)
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

VERIFIED_CUSTOMER_ID = "gid://shopify/Customer/1001"
OTHER_CUSTOMER_ID = "gid://shopify/Customer/9999"


def _verified_identity(customer_id: str = VERIFIED_CUSTOMER_ID) -> dict:
    return {
        "outcome": "verified_customer",
        "shopify_customer_id": customer_id,
        "company_name": "Acme Fleet",
    }


def _ctx(identity: dict | None = None) -> ToolExecutionContext:
    return ToolExecutionContext(
        profile="customer_service_external", identity=identity
    )


def _call(
    action: str,
    params: dict,
    *,
    identity: dict | None = None,
    driver: MockDriver | None = None,
):
    return execute_tool(
        tool="toee_easyroutes_read",
        action=action,
        params=params,
        context=_ctx(identity),
        driver=driver or MockDriver(create_easyroutes_mock_handlers()),
    )


# --- get_delivery_status -----------------------------------------------------


def test_get_delivery_status_returns_status_for_verified_owner() -> None:
    result = _call(
        "get_delivery_status", {"order_number": "1042"}, identity=_verified_identity()
    )

    assert result.ok is True
    assert result.data == {"order_number": "1042", "status": "in_transit"}


def test_get_delivery_status_blocks_unmatched_caller() -> None:
    result = _call("get_delivery_status", {"order_number": "1042"}, identity=None)

    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_get_delivery_status_blocks_another_owners_order() -> None:
    result = _call(
        "get_delivery_status",
        {"order_number": "1042"},
        identity=_verified_identity(OTHER_CUSTOMER_ID),
    )

    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_get_delivery_status_blocks_when_order_not_found() -> None:
    # Verified owner, but no delivery exists for this order: governed not-found.
    result = _call(
        "get_delivery_status", {"order_number": "9999"}, identity=_verified_identity()
    )

    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_get_delivery_status_output_is_snake_case_and_deterministic() -> None:
    first = _call(
        "get_delivery_status", {"order_number": "1042"}, identity=_verified_identity()
    )
    second = _call(
        "get_delivery_status", {"order_number": "1042"}, identity=_verified_identity()
    )

    assert first.data == second.data
    assert set(first.data.keys()) == {"order_number", "status"}
    assert "orderNumber" not in first.data


# --- get_route_details -------------------------------------------------------


def test_get_route_details_returns_details_for_verified_owner() -> None:
    result = _call(
        "get_route_details", {"order_number": "1042"}, identity=_verified_identity()
    )

    assert result.ok is True
    assert result.data == {
        "order_number": "1042",
        "stop_sequence": 4,
        "eta_window": "2026-01-02T14:00:00Z/2026-01-02T16:00:00Z",
        "route_name": "Route 7 - GTA West",
    }
    assert "stop_sequence" in result.data


def test_get_route_details_blocks_unmatched_caller() -> None:
    result = _call("get_route_details", {"order_number": "1042"}, identity=None)

    assert result.ok is False
    assert result.error_class == "policy_blocked"


# --- data injection ----------------------------------------------------------


def test_reads_deliveries_from_injected_factory_data() -> None:
    driver = MockDriver(
        create_easyroutes_mock_handlers(
            EasyroutesMockData(
                deliveries=[
                    EasyroutesDelivery(
                        order_number="3000",
                        shopify_customer_id=VERIFIED_CUSTOMER_ID,
                        status="delivered",
                        stop_sequence=1,
                        eta_window="2026-01-02T09:00:00Z/2026-01-02T11:00:00Z",
                        route_name="Injected Route",
                    )
                ]
            )
        )
    )

    result = _call(
        "get_delivery_status",
        {"order_number": "3000"},
        identity=_verified_identity(),
        driver=driver,
    )

    assert result.ok is True
    assert result.data == {"order_number": "3000", "status": "delivered"}


# --- governed boundary -------------------------------------------------------


def test_missing_mock_handler_is_governed_configuration_missing() -> None:
    # The easyroutes-only registry has no toee_shopify_read handler; the driver
    # must surface a governed failure, not raise.
    result = execute_tool(
        tool="toee_shopify_read",
        action="get_order",
        params={"order_id": "1"},
        context=_ctx(_verified_identity()),
        driver=MockDriver(create_easyroutes_mock_handlers()),
    )

    assert result.ok is False
    assert result.error_class == "configuration_missing"
