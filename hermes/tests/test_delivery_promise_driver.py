"""Delivery-promise driver (0.0.4 S31b): consumer of the owner's live
``POST /internal/hermes/delivery-promise`` endpoint (Tier 2 order status +
Tier 3a product promise).

Exercises governance, fail-closed, deadline, and mock-parity against a FAKE
:class:`DeliveryPromiseClient` — no network. The live HTTP client
(``_HttpDeliveryPromiseClient``) is deliberately not unit-tested (it needs the
network + the owner's secret, like the QBO gadget client and the Composio SDK
adapter); the live dev-endpoint e2e is the separate honestly-reported step.

Every call runs through the governed boundary (``execute_tool``) so the verified
gate, the endpoint's 404 ownership fail-closed, the empty-but-successful promise
relay, and the deadline all land as governed results, never raises that escape
dispatch.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import pytest

from toee_hermes.drivers.delivery.driver import (
    DeliveryPromiseClient,
    DeliveryPromiseDriver,
    build_delivery_promise_driver,
)
from toee_hermes.drivers.mock.delivery import create_delivery_mock_handlers
from toee_hermes.drivers.mock.driver import MockDriver
from toee_hermes.errors import ToolDriverError
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

DELIVERY_TOOL = "toee_delivery_promise"
# Si Li (the live dev-endpoint fixture customer).
VERIFIED_CUSTOMER_ID = "gid://shopify/Customer/1019382595648"
VERIFIED_NUMERIC = "1019382595648"
ORDER_ID = "7189924970579"
ORDER_NAME = "OL49597"
VARIANT_ID = "39379581042771"
SKU = "TRIM00014"
POSTAL = "M3J 1P3"

# Tier 2 200 body shape (S31a confirmed contract).
TIER2_BODY = {
    "traceId": "trace-t2",
    "tier": "order_status",
    "operation": "hermes_order_delivery",
    "orderId": ORDER_ID,
    "orderName": "OL49597",
    "delivery": {
        "status": "out_for_delivery",
        "statusHeadline": "Out for delivery today",
        "statusDetail": "On route Oakville Local #9813.",
        "deliveredAt": None,
        "routeLabel": "Oakville Local #9813",
        "estimatedReturnAt": "2026-07-24T21:00:00Z",
        "paymentMethodLabel": "Paid online",
        "pod": {"photoUrls": [], "note": None},
        "disclaimer": "Times are estimates and may change.",
    },
}

# Tier 3a 200 body — a cold-start `address_missing` promise: a REAL success the
# endpoint answers with customer-safe prose, NOT an error.
TIER3A_ADDRESS_MISSING = {
    "traceId": "trace-t3",
    "tier": "product_promise",
    "operation": "hermes_delivery_product_promise",
    "businessDate": "2026-07-24",
    "timezone": "America/Toronto",
    "variantId": VARIANT_ID,
    "sku": SKU,
    "quantity": 1,
    "productDeliveryPromise": {
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
    },
}

# Tier 3b 200 body — a PUBLIC quote by postal code, NO customer id. Dev returns an
# honest non-committal status (here variant_unavailable), relayed verbatim.
TIER3B_QUOTE = {
    "tier": "product_promise_quote",
    "operation": "hermes_delivery_quote",
    "postalCode": POSTAL,
    "fsa": "M3J",
    "variantId": VARIANT_ID,
    "sku": SKU,
    "quantity": 1,
    "productDeliveryPromise": {
        "status": "variant_unavailable",
        "deliveryTiming": "unknown",
        "displayLine": "We can't confirm delivery timing for this item to that area.",
        "disclaimer": "Delivery availability depends on your area.",
        "marketingCutoffLocal": "12:00",
        "countdownSeconds": None,
        "orderByDeadline": None,
        "servingWarehouseLabel": None,
        "serviceZoneLabel": None,
    },
}


class FakeClient:
    """Injectable client: records the posted payload, returns a canned body or raises."""

    def __init__(
        self,
        body: Optional[dict[str, Any]] = None,
        *,
        raises: Optional[Exception] = None,
        sleep_s: float = 0.0,
    ) -> None:
        self._body = body or {}
        self._raises = raises
        self._sleep_s = sleep_s
        self.payloads: list[dict[str, Any]] = []

    def fetch(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payloads.append(payload)
        if self._sleep_s:
            time.sleep(self._sleep_s)
        if self._raises is not None:
            raise self._raises
        return self._body


def _ctx(identity: Optional[dict] = None) -> ToolExecutionContext:
    return ToolExecutionContext(profile="customer_service_external", identity=identity)


def _verified(customer_id: str = VERIFIED_CUSTOMER_ID) -> dict:
    return {"outcome": "verified_customer", "shopify_customer_id": customer_id}


def _call(driver: DeliveryPromiseDriver, action: str, params: dict, *, identity=None):
    return execute_tool(
        tool=DELIVERY_TOOL,
        action=action,
        params=params,
        context=_ctx(identity),
        driver=driver,
    )


def _driver(client: DeliveryPromiseClient, **kw: Any) -> DeliveryPromiseDriver:
    return DeliveryPromiseDriver(client, **kw)


# --- Tier 2 happy path -------------------------------------------------------


def test_tier2_returns_delivery_block_for_verified_customer() -> None:
    client = FakeClient(TIER2_BODY)
    result = _call(
        _driver(client), "get_order_delivery", {"order_name": ORDER_NAME}, identity=_verified()
    )
    assert result.ok is True
    assert result.data["order_id"] == ORDER_ID
    assert result.data["order_name"] == "OL49597"
    assert result.data["delivery"] == TIER2_BODY["delivery"]
    # The verified customer's NUMERIC id is sent as shopifyCustomerId, never a
    # model-supplied one; the customer-facing ORDER NAME is sent as orderName (which the
    # agent sources from get_order's order_number — the reachability fix).
    assert client.payloads[0] == {"orderName": ORDER_NAME, "shopifyCustomerId": VERIFIED_NUMERIC}


# --- Tier 3a happy path + empty-but-successful relay -------------------------


def test_tier3a_by_sku_reaches_endpoint_and_relays_promise() -> None:
    # The reachability fix: the agent supplies a SKU (sourced from get_product's variants),
    # sent as `sku`; the endpoint resolves it to a variant and echoes both.
    client = FakeClient(TIER3A_ADDRESS_MISSING)
    result = _call(
        _driver(client),
        "get_product_promise",
        {"sku": SKU, "quantity": 2},
        identity=_verified(),
    )
    assert result.ok is True
    assert result.data["variant_id"] == VARIANT_ID
    assert result.data["sku"] == SKU
    assert result.data["product_delivery_promise"]["status"] == "address_missing"
    # The endpoint's customer-safe prose is relayed verbatim.
    assert (
        result.data["product_delivery_promise"]["displayLine"]
        == "Add a delivery address to see when this arrives."
    )
    assert client.payloads[0] == {
        "shopifyCustomerId": VERIFIED_NUMERIC,
        "sku": SKU,
        "quantity": 2,
    }


def test_tier3a_by_variant_id_still_works_backward_compat() -> None:
    client = FakeClient(TIER3A_ADDRESS_MISSING)
    result = _call(
        _driver(client),
        "get_product_promise",
        {"variant_id": VARIANT_ID},
        identity=_verified(),
    )
    assert result.ok is True
    assert client.payloads[0] == {"shopifyCustomerId": VERIFIED_NUMERIC, "variantId": VARIANT_ID}


def test_tier3a_address_missing_is_a_success_not_an_error() -> None:
    # The whole point of the empty-but-successful contract: a cold-start
    # address_missing is a REAL answer (ok=True), never a Tool Unavailable.
    result = _call(
        _driver(FakeClient(TIER3A_ADDRESS_MISSING)),
        "get_product_promise",
        {"sku": SKU},
        identity=_verified(),
    )
    assert result.ok is True


def test_tier3a_omits_quantity_when_not_supplied() -> None:
    client = FakeClient(TIER3A_ADDRESS_MISSING)
    _call(_driver(client), "get_product_promise", {"sku": SKU}, identity=_verified())
    assert client.payloads[0] == {"shopifyCustomerId": VERIFIED_NUMERIC, "sku": SKU}


def test_get_order_delivery_without_name_fails_closed_before_http() -> None:
    client = FakeClient(TIER2_BODY)
    result = _call(_driver(client), "get_order_delivery", {}, identity=_verified())
    assert result.ok is False
    assert result.error_class == "policy_blocked"
    assert client.payloads == []


def test_get_product_promise_without_sku_or_variant_fails_closed_before_http() -> None:
    client = FakeClient(TIER3A_ADDRESS_MISSING)
    result = _call(_driver(client), "get_product_promise", {}, identity=_verified())
    assert result.ok is False
    assert result.error_class == "policy_blocked"
    assert client.payloads == []


# --- ownership / verified gate (ADR-0043) ------------------------------------


def test_unverified_caller_fails_closed_before_any_http_call() -> None:
    client = FakeClient(TIER2_BODY)
    result = _call(_driver(client), "get_order_delivery", {"order_name": ORDER_NAME})
    assert result.ok is False
    assert result.error_class == "policy_blocked"
    # No lookup was attempted for an unverified caller.
    assert client.payloads == []


def test_tier3a_unverified_caller_fails_closed() -> None:
    client = FakeClient(TIER3A_ADDRESS_MISSING)
    result = _call(_driver(client), "get_product_promise", {"sku": SKU})
    assert result.ok is False
    assert result.error_class == "policy_blocked"
    assert client.payloads == []


# --- fail-closed: endpoint faults never fabricate a delivery -----------------


def test_404_ownership_mismatch_fails_closed_as_not_found() -> None:
    # The endpoint enforces order.customer.id === shopifyCustomerId and 404s a
    # non-owned order without revealing existence -> governed not_found.
    fault = ToolDriverError("not_found", "Delivery HTTP 404.")
    result = _call(
        _driver(FakeClient(raises=fault)),
        "get_order_delivery",
        {"order_name": ORDER_NAME},
        identity=_verified(),
    )
    assert result.ok is False
    assert result.error_class == "not_found"


def test_401_bad_bearer_fails_closed_as_auth() -> None:
    fault = ToolDriverError("auth_expired", "Delivery HTTP 401.")
    result = _call(
        _driver(FakeClient(raises=fault)),
        "get_order_delivery",
        {"order_name": ORDER_NAME},
        identity=_verified(),
    )
    assert result.ok is False
    assert result.error_class == "auth_expired"


def test_503_transient_fails_closed_as_vendor_timeout() -> None:
    fault = ToolDriverError("vendor_timeout", "Delivery HTTP 503.")
    result = _call(
        _driver(FakeClient(raises=fault)),
        "get_product_promise",
        {"sku": SKU},
        identity=_verified(),
    )
    assert result.ok is False
    assert result.error_class == "vendor_timeout"


def test_unclassified_client_error_becomes_governed_not_a_raw_raise() -> None:
    result = _call(
        _driver(FakeClient(raises=RuntimeError("socket exploded"))),
        "get_order_delivery",
        {"order_name": ORDER_NAME},
        identity=_verified(),
    )
    assert result.ok is False
    assert result.error_class == "configuration_missing"


def test_unexpected_body_shape_fails_closed_never_fabricates() -> None:
    # A 200 that carries neither `delivery` nor the expected block is a FAULT, never
    # an all-None fabricated delivery (ADR-0020, the S26 empty-vs-error trap).
    result = _call(
        _driver(FakeClient({"traceId": "x", "unexpected": "shape"})),
        "get_order_delivery",
        {"order_name": ORDER_NAME},
        identity=_verified(),
    )
    assert result.ok is False
    assert result.error_class == "configuration_missing"


# --- deadline bounds the whole call (NFR-8) ----------------------------------


def test_deadline_bounds_the_call() -> None:
    slow = FakeClient(TIER2_BODY, sleep_s=0.2)
    start = time.monotonic()
    result = _call(
        _driver(slow, deadline_ms=60),
        "get_order_delivery",
        {"order_name": ORDER_NAME},
        identity=_verified(),
    )
    elapsed = time.monotonic() - start
    assert result.ok is False
    assert result.error_class == "vendor_timeout"
    assert elapsed < 0.18


# --- mock parity -------------------------------------------------------------


def test_output_matches_the_mock_contract() -> None:
    mock = MockDriver(create_delivery_mock_handlers())
    real = _driver(FakeClient(TIER2_BODY))
    real_out = _call(real, "get_order_delivery", {"order_name": ORDER_NAME}, identity=_verified())
    mock_out = _call(mock, "get_order_delivery", {"order_name": ORDER_NAME}, identity=_verified())
    # Same top-level keys / structure so replay+eval exercise one contract.
    assert set(real_out.data) == set(mock_out.data)
    assert set(real_out.data["delivery"]) == set(mock_out.data["delivery"])


def test_mock_tier3a_returns_promise_block() -> None:
    mock = MockDriver(create_delivery_mock_handlers())
    out = _call(mock, "get_product_promise", {"sku": SKU}, identity=_verified())
    assert out.ok is True
    assert "product_delivery_promise" in out.data
    assert "displayLine" in out.data["product_delivery_promise"]


def test_tier3a_output_matches_the_mock_contract() -> None:
    mock = MockDriver(create_delivery_mock_handlers())
    real = _driver(FakeClient(TIER3A_ADDRESS_MISSING))
    real_out = _call(real, "get_product_promise", {"sku": SKU}, identity=_verified())
    mock_out = _call(mock, "get_product_promise", {"sku": SKU}, identity=_verified())
    assert set(real_out.data) == set(mock_out.data)
    assert set(real_out.data["product_delivery_promise"]) == set(
        mock_out.data["product_delivery_promise"]
    )


def test_mock_unknown_sku_fails_closed_like_the_endpoint_404() -> None:
    mock = MockDriver(create_delivery_mock_handlers())
    out = _call(mock, "get_product_promise", {"sku": "NOPE-000"}, identity=_verified())
    assert out.ok is False
    assert out.error_class == "not_found"


def test_mock_unverified_fails_closed() -> None:
    mock = MockDriver(create_delivery_mock_handlers())
    out = _call(mock, "get_order_delivery", {"order_name": ORDER_NAME})
    assert out.ok is False
    assert out.error_class == "policy_blocked"


# --- configuration fail-closed (missing secret, FR-21) -----------------------


def test_missing_secret_builds_a_driver_that_fails_closed_per_call(monkeypatch) -> None:
    monkeypatch.delenv("GADGET_API_KEY", raising=False)
    driver = build_delivery_promise_driver()  # total — must not raise
    result = _call(driver, "get_order_delivery", {"order_name": ORDER_NAME}, identity=_verified())
    assert result.ok is False
    assert result.error_class == "configuration_missing"


def test_build_with_secret_yields_a_live_client_driver(monkeypatch) -> None:
    monkeypatch.setenv("GADGET_API_KEY", "secret-123")
    driver = build_delivery_promise_driver()
    assert driver.kind == "delivery_promise"
    assert driver._config_error is None
    assert driver._client is not None


# --- Tier 3b: PUBLIC quote by postal, unverified-allowed (S32) ---------------


def test_quote_reachable_by_unverified_caller_and_sends_no_customer_id() -> None:
    # THE key S32 test: the same UNVERIFIED caller who is failed closed for the two
    # account actions can successfully get a public area-level quote. And the payload
    # carries NO shopifyCustomerId — it can never disclose a specific customer's data.
    client = FakeClient(TIER3B_QUOTE)
    result = _call(
        _driver(client),
        "get_delivery_quote",
        {"sku": SKU, "postal_code": POSTAL},
        identity=None,  # unmatched / unverified prospect
    )
    assert result.ok is True
    assert result.data["postal_code"] == POSTAL
    assert result.data["fsa"] == "M3J"
    assert result.data["sku"] == SKU
    assert result.data["variant_id"] == VARIANT_ID
    # No customer id anywhere in the payload sent to the endpoint.
    assert client.payloads[0] == {"postalCode": POSTAL, "sku": SKU}
    assert "shopifyCustomerId" not in client.payloads[0]


def test_quote_public_where_account_actions_fail_closed_for_same_unverified_caller() -> None:
    # The asymmetry, side by side: order/promise fail closed for an unverified caller,
    # the quote succeeds — same caller, same driver, same turn.
    order = _call(_driver(FakeClient(TIER2_BODY)), "get_order_delivery", {"order_name": ORDER_NAME})
    promise = _call(_driver(FakeClient(TIER3A_ADDRESS_MISSING)), "get_product_promise", {"sku": SKU})
    quote = _call(
        _driver(FakeClient(TIER3B_QUOTE)), "get_delivery_quote", {"sku": SKU, "postal_code": POSTAL}
    )
    assert (order.ok, order.error_class) == (False, "policy_blocked")
    assert (promise.ok, promise.error_class) == (False, "policy_blocked")
    assert quote.ok is True


def test_quote_by_variant_id_still_works_and_sends_no_customer_id() -> None:
    client = FakeClient(TIER3B_QUOTE)
    result = _call(
        _driver(client),
        "get_delivery_quote",
        {"variant_id": VARIANT_ID, "postal_code": POSTAL, "quantity": 2},
        identity=None,
    )
    assert result.ok is True
    assert client.payloads[0] == {"postalCode": POSTAL, "variantId": VARIANT_ID, "quantity": 2}


def test_quote_without_postal_fails_closed_before_http() -> None:
    client = FakeClient(TIER3B_QUOTE)
    result = _call(_driver(client), "get_delivery_quote", {"sku": SKU}, identity=None)
    assert result.ok is False
    assert result.error_class == "policy_blocked"
    assert client.payloads == []


def test_quote_without_sku_fails_closed_before_http() -> None:
    client = FakeClient(TIER3B_QUOTE)
    result = _call(_driver(client), "get_delivery_quote", {"postal_code": POSTAL}, identity=None)
    assert result.ok is False
    assert result.error_class == "policy_blocked"
    assert client.payloads == []


def test_quote_malformed_postal_400_fails_closed() -> None:
    # The endpoint 400s a malformed postal -> the HTTP client maps 400 to
    # configuration_missing; a bad postal is a governed failure, never a fabricated ETA.
    fault = ToolDriverError("configuration_missing", "Delivery HTTP 400.")
    result = _call(
        _driver(FakeClient(raises=fault)),
        "get_delivery_quote",
        {"sku": SKU, "postal_code": "NOTAPOSTAL"},
        identity=None,
    )
    assert result.ok is False
    assert result.error_class == "configuration_missing"


def test_quote_unknown_sku_404_fails_closed() -> None:
    fault = ToolDriverError("not_found", "Delivery HTTP 404.")
    result = _call(
        _driver(FakeClient(raises=fault)),
        "get_delivery_quote",
        {"sku": "NOPE-000", "postal_code": POSTAL},
        identity=None,
    )
    assert result.ok is False
    assert result.error_class == "not_found"


def test_quote_unserved_area_is_relayed_honestly_not_fabricated() -> None:
    # A 200 with route_unavailable/variant_unavailable is a REAL answer relayed via the
    # endpoint's own displayLine — ok=True, never upgraded to a positive date.
    result = _call(
        _driver(FakeClient(TIER3B_QUOTE)),
        "get_delivery_quote",
        {"sku": SKU, "postal_code": POSTAL},
        identity=None,
    )
    assert result.ok is True
    promise = result.data["product_delivery_promise"]
    assert promise["status"] == "variant_unavailable"
    assert promise["displayLine"] == "We can't confirm delivery timing for this item to that area."


# --- Tier 3b mock parity + resolution ----------------------------------------


def test_quote_mock_reachable_by_unverified_and_matches_contract() -> None:
    mock = MockDriver(create_delivery_mock_handlers())
    real = _driver(FakeClient(TIER3B_QUOTE))
    real_out = _call(real, "get_delivery_quote", {"sku": SKU, "postal_code": POSTAL}, identity=None)
    mock_out = _call(mock, "get_delivery_quote", {"sku": SKU, "postal_code": POSTAL}, identity=None)
    assert mock_out.ok is True  # unverified caller succeeds against the mock too
    assert set(real_out.data) == set(mock_out.data)
    assert set(real_out.data["product_delivery_promise"]) == set(
        mock_out.data["product_delivery_promise"]
    )


def test_quote_mock_unknown_sku_fails_closed_like_404() -> None:
    mock = MockDriver(create_delivery_mock_handlers())
    out = _call(mock, "get_delivery_quote", {"sku": "NOPE-000", "postal_code": POSTAL}, identity=None)
    assert out.ok is False
    assert out.error_class == "not_found"


def test_quote_mock_malformed_postal_fails_closed_like_400() -> None:
    mock = MockDriver(create_delivery_mock_handlers())
    out = _call(mock, "get_delivery_quote", {"sku": SKU, "postal_code": "NOPE"}, identity=None)
    assert out.ok is False
    assert out.error_class == "configuration_missing"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
