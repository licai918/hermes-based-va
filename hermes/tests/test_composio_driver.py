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
CONVERSATION_ID = "sms:conv_abc123"
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


def test_qbo_get_ar_summary_fails_closed_without_gadget_key() -> None:
    # 0.0.4 S13: the AR summary is now computed from the customer's OWN attributed
    # invoices (S27 list path), NOT the all-customer aged-receivables report. With no
    # attributor (no Gadget key) the live path cannot positively attribute, so it
    # fails closed (configuration_missing) rather than fabricating an empty "$0".
    client = FakeComposioClient(_live_list_raw())
    with pytest.raises(ToolDriverError) as excinfo:
        _run(client, "toee_qbo_read", "get_ar_summary", {}, _ctx(identity=_verified()))
    assert excinfo.value.error_class == "configuration_missing"


def test_qbo_get_invoice_hides_another_customers_invoice() -> None:
    # A verified customer must not receive an invoice owned by a different customer.
    raw = {
        "invoice": {
            "invoice_number": "INV-OTHER",
            "shopify_customer_id": "gid://shopify/Customer/9999",
            "customer_email": "other@example.com",
            "balance": 42.0,
        }
    }
    client = FakeComposioClient(raw)
    with pytest.raises(ToolDriverError) as excinfo:
        _run(
            client,
            "toee_qbo_read",
            "get_invoice",
            {"invoice_number": "INV-OTHER"},
            _ctx(identity=_verified()),
        )
    assert excinfo.value.error_class == "not_found"


def test_qbo_list_customer_invoices_drops_other_customers() -> None:
    raw = {
        "invoices": [
            {
                "invoice_number": "INV-MINE",
                "shopify_customer_id": VERIFIED_CUSTOMER_ID,
                "customer_email": "me@example.com",
                "balance": 100.0,
            },
            {
                "invoice_number": "INV-THEIRS",
                "shopify_customer_id": "gid://shopify/Customer/9999",
                "customer_email": "other@example.com",
                "balance": 999.0,
            },
        ]
    }
    client = FakeComposioClient(raw)
    out = _run(
        client, "toee_qbo_read", "list_customer_invoices", {}, _ctx(identity=_verified())
    )
    assert [inv["invoice_number"] for inv in out] == ["INV-MINE"]


# --- qbo LIVE attribution via the Gadget bridge (0.0.4 S27) -------------------
#
# Live QBO invoices carry only ``CustomerRef.value`` (a QBO customer id), NOT a
# Shopify id. Attribution then requires the Gadget qboCustomerMapping join under the
# owner's trust rule. The pre-S27 bug returned an empty SUCCESS ("you have no
# invoices") to every verified customer because it compared an absent
# shopify_customer_id field; these tests pin the fail-closed replacement.

QBO_CUSTOMER_ID = "QBO-77"


class FakeAttributor:
    """Stand-in for QboAttribution: maps one QBO customer id to the verified GID."""

    def __init__(self, *, qbo_id: str | None, error: Exception | None = None) -> None:
        self._qbo_id = qbo_id
        self._error = error

    def qbo_customer_id_for(self, verified_gid: str) -> str:
        if self._error is not None:
            raise self._error
        if self._qbo_id is None:
            raise ToolDriverError("configuration_missing", "no trusted mapping")
        return self._qbo_id

    def invoice_owned_by(self, qbo_customer_id: str, verified_gid: str) -> bool:
        if self._error is not None:
            raise self._error
        if self._qbo_id is None:
            raise ToolDriverError("configuration_missing", "no trusted mapping")
        return qbo_customer_id == self._qbo_id


def _driver_with_attr(client: FakeComposioClient, attributor: Any) -> ComposioDriver:
    return ComposioDriver(
        client,
        user_id=USER_ID,
        connected_accounts=CONNECTED_ACCOUNTS,
        attributor=attributor,
    )


def _live_list_raw() -> dict[str, Any]:
    # QBO QueryResponse shape: no shopify_customer_id, CustomerRef carries the QBO id.
    return {
        "QueryResponse": {
            "Invoice": [
                {
                    "DocNumber": "OL49942",
                    "CustomerRef": {"value": QBO_CUSTOMER_ID, "name": "Acme"},
                    "BillEmail": {"Address": "acme@example.com"},
                    "Balance": 804.56,
                },
                {
                    "DocNumber": "OTHER-1",
                    "CustomerRef": {"value": "QBO-OTHER", "name": "Someone"},
                    "Balance": 10.0,
                },
            ]
        }
    }


def test_qbo_list_live_attributes_owned_invoice_via_gadget() -> None:
    client = FakeComposioClient(_live_list_raw())
    driver = _driver_with_attr(client, FakeAttributor(qbo_id=QBO_CUSTOMER_ID))
    out = driver.execute(
        ToolRequest(tool="toee_qbo_read", action="list_customer_invoices", params={}),
        _ctx(identity=_verified()),
    )
    assert [inv["invoice_number"] for inv in out] == ["OL49942"]
    # The private qbo_customer_id never leaks into the public contract.
    assert set(out[0].keys()) == {
        "invoice_number",
        "shopify_customer_id",
        "customer_email",
        "balance",
    }


def test_qbo_list_live_fails_closed_on_qbo_id_collision_does_not_leak() -> None:
    # A1 cross-customer disclosure: two DIFFERENT trusted Shopify customers both map
    # to the SAME QBO id. Listing every invoice billed to that QBO id would hand the
    # other customer's invoices to this one. Wired against a REAL QboAttribution over
    # a fake Gadget client returning both trusted mappings, list_customer_invoices
    # must fail closed and NOT return the qbo_X invoice. (Revert the guard in
    # gadget.qbo_customer_id_for and this leaks OL49942 to gid 1001.)
    from toee_hermes.drivers.gadget import QboAttribution

    class _CollidingGadget:
        def query_customer_mappings(self, **_: Any) -> list[dict[str, Any]]:
            return [
                {"id": "a", "qboCustomerId": QBO_CUSTOMER_ID,
                 "shopifyCustomerGid": VERIFIED_CUSTOMER_ID, "status": "AUTO_MATCHED"},
                {"id": "b", "qboCustomerId": QBO_CUSTOMER_ID,
                 "shopifyCustomerGid": "gid://shopify/Customer/2002", "status": "AUTO_MATCHED"},
            ]

    client = FakeComposioClient(_live_list_raw())
    driver = _driver_with_attr(client, QboAttribution(_CollidingGadget()))
    with pytest.raises(ToolDriverError):
        driver.execute(
            ToolRequest(tool="toee_qbo_read", action="list_customer_invoices", params={}),
            _ctx(identity=_verified()),
        )


def test_qbo_list_live_matches_across_qbo_id_representations() -> None:
    # Canonicalization: the mapping resolves QBO id "4902" but the invoice carries the
    # int 4902 (and a leading-zero sibling). Raw-string compare would deny the legit
    # customer their own invoice; canonical compare matches both.
    raw = {
        "QueryResponse": {
            "Invoice": [
                {"DocNumber": "N-1", "CustomerRef": {"value": 4902}, "Balance": 1.0},
                {"DocNumber": "N-2", "CustomerRef": {"value": "004902"}, "Balance": 2.0},
                {"DocNumber": "N-3", "CustomerRef": {"value": "5000"}, "Balance": 3.0},
            ]
        }
    }
    client = FakeComposioClient(raw)
    driver = _driver_with_attr(client, FakeAttributor(qbo_id="4902"))
    out = driver.execute(
        ToolRequest(tool="toee_qbo_read", action="list_customer_invoices", params={}),
        _ctx(identity=_verified()),
    )
    assert sorted(inv["invoice_number"] for inv in out) == ["N-1", "N-2"]


def test_qbo_list_live_fails_closed_when_unattributable() -> None:
    # The S27 regression: a live customer whose mapping is missing/unconfirmed must
    # get a governed unavailable, NEVER an empty "you have no invoices" success.
    client = FakeComposioClient(_live_list_raw())
    driver = _driver_with_attr(client, FakeAttributor(qbo_id=None))
    with pytest.raises(ToolDriverError):
        driver.execute(
            ToolRequest(tool="toee_qbo_read", action="list_customer_invoices", params={}),
            _ctx(identity=_verified()),
        )


def test_qbo_list_live_fails_closed_on_gadget_fault() -> None:
    client = FakeComposioClient(_live_list_raw())
    driver = _driver_with_attr(
        client, FakeAttributor(qbo_id=None, error=ToolDriverError("vendor_timeout", "slow"))
    )
    with pytest.raises(ToolDriverError) as excinfo:
        driver.execute(
            ToolRequest(tool="toee_qbo_read", action="list_customer_invoices", params={}),
            _ctx(identity=_verified()),
        )
    assert excinfo.value.error_class == "vendor_timeout"


def test_qbo_list_live_empty_page_fails_closed_when_unattributable() -> None:
    # Even a genuinely empty vendor page must fail closed for an unattributable
    # customer, so "you have none" is never narrated without a trusted mapping.
    client = FakeComposioClient({"QueryResponse": {"Invoice": []}})
    driver = _driver_with_attr(client, FakeAttributor(qbo_id=None))
    with pytest.raises(ToolDriverError):
        driver.execute(
            ToolRequest(tool="toee_qbo_read", action="list_customer_invoices", params={}),
            _ctx(identity=_verified()),
        )


def test_qbo_list_live_default_driver_fails_closed_without_gadget_key() -> None:
    # A ComposioDriver built without an attributor (no Gadget key) fails closed on a
    # live QBO read rather than returning an empty success.
    client = FakeComposioClient(_live_list_raw())
    with pytest.raises(ToolDriverError) as excinfo:
        _run(client, "toee_qbo_read", "list_customer_invoices", {}, _ctx(identity=_verified()))
    assert excinfo.value.error_class == "configuration_missing"


# --- qbo get_ar_summary (0.0.4 S13, FR-19) -----------------------------------
#
# The AR summary is computed from the verified customer's OWN attributed invoices
# (the S27 list path), NOT the all-customer aged-receivables report. So it inherits
# every S27 fail-closed arm, and an unattributable summary is a governed unavailable
# -- never a fabricated/empty "$0". A positively-attributed customer with zero open
# invoices is an honest $0 (empty-vs-error distinction on the success side).

VERIFIED_AR_SHAPE = {"shopify_customer_id", "open_invoice_count", "total_balance"}


def test_qbo_ar_summary_aggregates_owned_via_gadget() -> None:
    # Live shape: only OL49942 (QBO_CUSTOMER_ID) is owned; OTHER-1 (QBO-OTHER) is not.
    client = FakeComposioClient(_live_list_raw())
    driver = _driver_with_attr(client, FakeAttributor(qbo_id=QBO_CUSTOMER_ID))
    out = driver.execute(
        ToolRequest(tool="toee_qbo_read", action="get_ar_summary", params={}),
        _ctx(identity=_verified()),
    )
    assert out == {
        "shopify_customer_id": VERIFIED_CUSTOMER_ID,
        "open_invoice_count": 1,
        "total_balance": 804.56,
    }
    # No invoice list, no private qbo_customer_id -- only the 3 public summary keys.
    assert set(out.keys()) == VERIFIED_AR_SHAPE


def test_qbo_ar_summary_direct_linkage_drops_other_customers() -> None:
    raw = {
        "invoices": [
            {"invoice_number": "INV-MINE", "shopify_customer_id": VERIFIED_CUSTOMER_ID,
             "customer_email": "me@example.com", "balance": 100.0},
            {"invoice_number": "INV-ALSO-MINE", "shopify_customer_id": VERIFIED_CUSTOMER_ID,
             "customer_email": "me@example.com", "balance": 50.0},
            {"invoice_number": "INV-THEIRS", "shopify_customer_id": "gid://shopify/Customer/9999",
             "customer_email": "other@example.com", "balance": 999.0},
        ]
    }
    client = FakeComposioClient(raw)
    out = _run(client, "toee_qbo_read", "get_ar_summary", {}, _ctx(identity=_verified()))
    assert out == {
        "shopify_customer_id": VERIFIED_CUSTOMER_ID,
        "open_invoice_count": 2,
        "total_balance": 150.0,
    }


def test_qbo_ar_summary_honest_zero_when_attributed_but_no_open_invoices() -> None:
    # Positively attributed (qbo id resolves) but NONE of the listed invoices are
    # theirs -> honest $0, NOT an error. This is the empty-vs-error success side.
    client = FakeComposioClient(_live_list_raw())
    driver = _driver_with_attr(client, FakeAttributor(qbo_id="QBO-NOBODY"))
    out = driver.execute(
        ToolRequest(tool="toee_qbo_read", action="get_ar_summary", params={}),
        _ctx(identity=_verified()),
    )
    assert out == {
        "shopify_customer_id": VERIFIED_CUSTOMER_ID,
        "open_invoice_count": 0,
        "total_balance": 0,
    }


def test_qbo_ar_summary_excludes_paid_invoices() -> None:
    # "open" = balance > 0. A fully-paid (balance 0) owned invoice is not receivable.
    raw = {
        "invoices": [
            {"invoice_number": "INV-OPEN", "shopify_customer_id": VERIFIED_CUSTOMER_ID,
             "customer_email": "me@example.com", "balance": 300.0},
            {"invoice_number": "INV-PAID", "shopify_customer_id": VERIFIED_CUSTOMER_ID,
             "customer_email": "me@example.com", "balance": 0},
        ]
    }
    client = FakeComposioClient(raw)
    out = _run(client, "toee_qbo_read", "get_ar_summary", {}, _ctx(identity=_verified()))
    assert out["open_invoice_count"] == 1
    assert out["total_balance"] == 300.0


def test_qbo_ar_summary_fails_closed_when_unattributable() -> None:
    # No trusted mapping -> RAISE, never an empty/fabricated "$0 owing".
    client = FakeComposioClient(_live_list_raw())
    driver = _driver_with_attr(client, FakeAttributor(qbo_id=None))
    with pytest.raises(ToolDriverError):
        driver.execute(
            ToolRequest(tool="toee_qbo_read", action="get_ar_summary", params={}),
            _ctx(identity=_verified()),
        )


def test_qbo_ar_summary_fails_closed_on_gadget_fault() -> None:
    client = FakeComposioClient(_live_list_raw())
    driver = _driver_with_attr(
        client, FakeAttributor(qbo_id=None, error=ToolDriverError("vendor_timeout", "slow"))
    )
    with pytest.raises(ToolDriverError) as excinfo:
        driver.execute(
            ToolRequest(tool="toee_qbo_read", action="get_ar_summary", params={}),
            _ctx(identity=_verified()),
        )
    assert excinfo.value.error_class == "vendor_timeout"


def test_qbo_ar_summary_fails_closed_on_qbo_id_collision_does_not_leak() -> None:
    # Same A1 cross-customer guard as listing: two trusted Shopify customers sharing
    # one QBO id must fail closed -- the AR summary must not become a way around it.
    from toee_hermes.drivers.gadget import QboAttribution

    class _CollidingGadget:
        def query_customer_mappings(self, **_: Any) -> list[dict[str, Any]]:
            return [
                {"id": "a", "qboCustomerId": QBO_CUSTOMER_ID,
                 "shopifyCustomerGid": VERIFIED_CUSTOMER_ID, "status": "AUTO_MATCHED"},
                {"id": "b", "qboCustomerId": QBO_CUSTOMER_ID,
                 "shopifyCustomerGid": "gid://shopify/Customer/2002", "status": "AUTO_MATCHED"},
            ]

    client = FakeComposioClient(_live_list_raw())
    driver = _driver_with_attr(client, QboAttribution(_CollidingGadget()))
    with pytest.raises(ToolDriverError):
        driver.execute(
            ToolRequest(tool="toee_qbo_read", action="get_ar_summary", params={}),
            _ctx(identity=_verified()),
        )


def test_qbo_ar_summary_requires_verified_customer() -> None:
    client = FakeComposioClient(_live_list_raw())
    driver = _driver_with_attr(client, FakeAttributor(qbo_id=QBO_CUSTOMER_ID))
    with pytest.raises(ToolDriverError) as excinfo:
        driver.execute(
            ToolRequest(tool="toee_qbo_read", action="get_ar_summary", params={}),
            _ctx(identity=None),
        )
    assert excinfo.value.error_class == "policy_blocked"


def test_qbo_get_invoice_live_attributes_via_gadget() -> None:
    raw = {
        "QueryResponse": {
            "Invoice": [
                {
                    "DocNumber": "OL49942",
                    "CustomerRef": {"value": QBO_CUSTOMER_ID},
                    "Balance": 804.56,
                }
            ]
        }
    }
    client = FakeComposioClient(raw)
    driver = _driver_with_attr(client, FakeAttributor(qbo_id=QBO_CUSTOMER_ID))
    out = driver.execute(
        ToolRequest(
            tool="toee_qbo_read", action="get_invoice", params={"invoice_number": "OL49942"}
        ),
        _ctx(identity=_verified()),
    )
    assert out["invoice_number"] == "OL49942"
    assert out["balance"] == 804.56


def test_qbo_get_invoice_live_fails_closed_when_not_owned() -> None:
    raw = {
        "QueryResponse": {
            "Invoice": [{"DocNumber": "X", "CustomerRef": {"value": "QBO-OTHER"}, "Balance": 5.0}]
        }
    }
    client = FakeComposioClient(raw)
    driver = _driver_with_attr(client, FakeAttributor(qbo_id=QBO_CUSTOMER_ID))
    with pytest.raises(ToolDriverError) as excinfo:
        driver.execute(
            ToolRequest(
                tool="toee_qbo_read", action="get_invoice", params={"invoice_number": "X"}
            ),
            _ctx(identity=_verified()),
        )
    assert excinfo.value.error_class == "not_found"


def test_qbo_reads_require_a_verified_customer() -> None:
    client = FakeComposioClient(_live_list_raw())
    driver = _driver_with_attr(client, FakeAttributor(qbo_id=QBO_CUSTOMER_ID))
    with pytest.raises(ToolDriverError) as excinfo:
        driver.execute(
            ToolRequest(tool="toee_qbo_read", action="list_customer_invoices", params={}),
            _ctx(identity=None),
        )
    assert excinfo.value.error_class == "policy_blocked"


# --- composio errors-in-success guard (0.0.4 S27 fold-in) --------------------


def test_composio_sdk_client_fails_closed_on_vendor_error_in_success() -> None:
    # Composio can report a VENDOR error as transport success: successful=true with
    # data carrying an errors array. The SDK adapter must fail closed, not pass it to
    # a mapper that would shape an all-None result (ADR-0020, the S26 Square shape).
    from toee_hermes.drivers.composio.driver import _ComposioSdkClient

    class FakeSdk:
        class tools:  # noqa: N801 - mirrors the SDK attribute path
            @staticmethod
            def execute(action, params, *, connected_account_id, user_id):  # noqa: ANN001
                return {
                    "successful": True,
                    "error": None,
                    "data": {"errors": [{"message": "missing scope"}], "payment_link": None},
                }

    client = _ComposioSdkClient(FakeSdk())
    with pytest.raises(ToolDriverError) as excinfo:
        client.execute_action(
            action="SQUARE_RETRIEVE_PAYMENT_LINK",
            params={"id": "x"},
            connected_account_id="ca_square",
            user_id=USER_ID,
        )
    assert excinfo.value.error_class == "composio_api_error"


def test_composio_sdk_client_passes_clean_success() -> None:
    from toee_hermes.drivers.composio.driver import _ComposioSdkClient

    class FakeSdk:
        class tools:  # noqa: N801
            @staticmethod
            def execute(action, params, *, connected_account_id, user_id):  # noqa: ANN001
                return {"successful": True, "error": None, "data": {"order": {"id": "1"}}}

    client = _ComposioSdkClient(FakeSdk())
    assert client.execute_action(
        action="SHOPIFY_GET_ORDERSBY_ID",
        params={},
        connected_account_id="ca_shopify",
        user_id=USER_ID,
    ) == {"order": {"id": "1"}}


# --- square ------------------------------------------------------------------


def test_square_send_payment_link_fails_closed_on_composio() -> None:
    # 0.0.4 S26: the owner switched this tool to RETRIEVE semantics, and
    # SQUARE_RETRIEVE_PAYMENT_LINK does resolve at pin 20260616_00 (S26 live
    # probe), so S12's reason -- "no such action" -- no longer holds. It is still
    # gated off for a different one: retrieve is by the Square-assigned link id,
    # nothing the agent legitimately holds maps to one, and no list/search action
    # exists at the pin to resolve one. Until the owner names a governed source for
    # that id the customer gets a governed unavailable result -- never a mock link,
    # and never a link belonging to another invoice. Texting a verified customer a
    # fabricated or wrong payment URL is the worst failure available here
    # (ADR-0020, ADR-0148, FR-21).
    spec = ACTION_MAPPING[("toee_square_payment_link", "send_payment_link")]
    assert spec.action_slug == "SQUARE_RETRIEVE_PAYMENT_LINK"

    client = FakeComposioClient({})
    with pytest.raises(ToolDriverError) as excinfo:
        _run(
            client,
            "toee_square_payment_link",
            "send_payment_link",
            {"invoice_number": "INV-9001"},
            _ctx(identity=_verified(), conversation_id=CONVERSATION_ID),
        )
    assert excinfo.value.error_class == "configuration_missing"
    assert client.calls == []  # never reached the backend


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
    # Slugs are verified live by `python -m hermes_runtime.composio_smoke` phase 2;
    # here we only hold the structural invariant. An entry is EITHER callable (both
    # mappers) or deliberately gated off (an `unavailable` error) -- never neither,
    # which would be a spec that raises TypeError mid-turn.
    for key, spec in ACTION_MAPPING.items():
        assert spec.action_slug
        assert spec.app in {"shopify", "qbo", "square"}
        callable_spec = spec.request_mapper is not None and spec.response_mapper is not None
        assert callable_spec != (spec.unavailable is not None), key
