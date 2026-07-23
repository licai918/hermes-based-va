"""EasyRoutes direct REST driver (0.0.4 S14, FR-20/21, NFR-8).

Exercises the governance, fail-closed, deadline, and mock-parity paths of the
real driver against a FAKE :class:`EasyroutesClient` — no network. The live HTTP
client (``_HttpEasyroutesClient``) is deliberately not unit-tested (it needs the
network + the account, like the Composio SDK adapter); a live smoke against the
owner's token is the separate honestly-reported step.

Every call runs through the governed boundary (``execute_tool``) so the ownership
block, the empty-vs-error distinction, and the deadline all land as governed
results, never raises that escape dispatch.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

import pytest

from toee_hermes.drivers.easyroutes.driver import (
    EasyroutesClient,
    EasyroutesDriver,
    _HttpEasyroutesClient,
    _shopify_customer_gid,
    build_easyroutes_driver,
)
from toee_hermes.drivers.mock.driver import MockDriver
from toee_hermes.drivers.mock.easyroutes import create_easyroutes_mock_handlers
from toee_hermes.errors import ToolDriverError
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

VERIFIED_CUSTOMER_ID = "gid://shopify/Customer/1001"
OTHER_CUSTOMER_ID = "gid://shopify/Customer/9999"

# A realistic-ish raw record (field paths are UNVERIFIED against the live API, so
# the driver reads several plausible spellings — mirror that here).
RAW_1042 = {
    "order_number": "1042",
    "shopify_customer_id": "1001",  # bare id -> driver normalizes to gid
    "status": "in_transit",
    "stop_sequence": 4,
    "eta_window": "2026-01-02T14:00:00Z/2026-01-02T16:00:00Z",
    "route_name": "Route 7 - GTA West",
}


class FakeClient:
    """Injectable client returning canned records, or raising a preset fault."""

    def __init__(
        self,
        records: Optional[list[dict[str, Any]]] = None,
        *,
        raises: Optional[Exception] = None,
        sleep_s: float = 0.0,
        sub_requests: int = 1,
    ) -> None:
        self._records = records or []
        self._raises = raises
        self._sleep_s = sleep_s
        self._sub_requests = sub_requests
        self.calls = 0

    def fetch_deliveries(self, *, order_number: Optional[str]) -> list[dict[str, Any]]:
        self.calls += 1
        # Simulate a call made of several sequential HTTP requests, to prove the
        # deadline bounds the WHOLE call, not one request (the S12 finding).
        for _ in range(self._sub_requests):
            if self._sleep_s:
                time.sleep(self._sleep_s)
        if self._raises is not None:
            raise self._raises
        return list(self._records)


def _ctx(identity: Optional[dict] = None) -> ToolExecutionContext:
    return ToolExecutionContext(profile="customer_service_external", identity=identity)


def _verified(customer_id: str = VERIFIED_CUSTOMER_ID) -> dict:
    return {"outcome": "verified_customer", "shopify_customer_id": customer_id}


def _call(
    driver: EasyroutesDriver,
    action: str,
    params: dict,
    *,
    identity: Optional[dict] = None,
):
    return execute_tool(
        tool="toee_easyroutes_read",
        action=action,
        params=params,
        context=_ctx(identity),
        driver=driver,
    )


def _driver(client: EasyroutesClient, **kw: Any) -> EasyroutesDriver:
    return EasyroutesDriver(client, **kw)


# --- happy path + mock parity ------------------------------------------------


def test_get_delivery_status_returns_status_for_verified_owner() -> None:
    result = _call(
        _driver(FakeClient([RAW_1042])),
        "get_delivery_status",
        {"order_number": "1042"},
        identity=_verified(),
    )
    assert result.ok is True
    assert result.data == {"order_number": "1042", "status": "in_transit"}


def test_get_route_details_returns_details_for_verified_owner() -> None:
    result = _call(
        _driver(FakeClient([RAW_1042])),
        "get_route_details",
        {"order_number": "1042"},
        identity=_verified(),
    )
    assert result.ok is True
    assert result.data == {
        "order_number": "1042",
        "stop_sequence": 4,
        "eta_window": "2026-01-02T14:00:00Z/2026-01-02T16:00:00Z",
        "route_name": "Route 7 - GTA West",
    }


def test_output_is_byte_for_byte_identical_to_the_mock_contract() -> None:
    # Parity is the whole point: the same delivery through the mock and through the
    # real driver must produce identical result dicts (FR-20 "aligned to the mock").
    mock = MockDriver(create_easyroutes_mock_handlers())
    real = _driver(FakeClient([RAW_1042]))
    for action in ("get_delivery_status", "get_route_details"):
        mock_out = _call(mock, action, {"order_number": "1042"}, identity=_verified())
        real_out = _call(real, action, {"order_number": "1042"}, identity=_verified())
        assert real_out.data == mock_out.data, action


# --- ownership (ADR-0043) ----------------------------------------------------


def test_blocks_unmatched_caller() -> None:
    result = _call(
        _driver(FakeClient([RAW_1042])), "get_delivery_status", {"order_number": "1042"}
    )
    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_blocks_another_owners_order() -> None:
    result = _call(
        _driver(FakeClient([RAW_1042])),
        "get_delivery_status",
        {"order_number": "1042"},
        identity=_verified(OTHER_CUSTOMER_ID),
    )
    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_record_without_a_resolvable_owner_fails_closed_as_non_owned() -> None:
    # The QBO/S26 lesson: an unattributable record must NOT match anyone.
    orphan = {**RAW_1042, "shopify_customer_id": None, "customer": None, "order": None}
    result = _call(
        _driver(FakeClient([orphan])),
        "get_delivery_status",
        {"order_number": "1042"},
        identity=_verified(),
    )
    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_shopify_customer_gid_normalizes_plausible_shapes() -> None:
    assert _shopify_customer_gid({"shopify_customer_id": "1001"}) == VERIFIED_CUSTOMER_ID
    assert _shopify_customer_gid({"shopifyCustomerId": VERIFIED_CUSTOMER_ID}) == VERIFIED_CUSTOMER_ID
    assert _shopify_customer_gid({"customer": {"id": 1001}}) == VERIFIED_CUSTOMER_ID
    assert _shopify_customer_gid({"order": {"customer": {"id": "1001"}}}) == VERIFIED_CUSTOMER_ID
    # No resolvable owner -> empty, which can never match a verified gid.
    assert _shopify_customer_gid({"nothing": "here"}) == ""


# --- fail-closed: empty-vs-error distinction (FR-21, S26 trap) ---------------


def test_empty_successful_response_is_a_governed_no_delivery_not_an_error() -> None:
    # A genuine 2xx-empty: the customer's order simply isn't routed yet. This is a
    # governed policy block (same as the mock's not-found), NOT unavailable.
    result = _call(
        _driver(FakeClient([])),
        "get_delivery_status",
        {"order_number": "1042"},
        identity=_verified(),
    )
    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_backend_fault_fails_closed_and_is_never_narrated_as_no_delivery() -> None:
    # A client fault (auth/5xx/parse) must surface as the fault's governed class,
    # never as an empty "no delivery" — the empty-vs-error distinction (FR-21).
    fault = ToolDriverError("auth_expired", "EasyRoutes HTTP 401.")
    result = _call(
        _driver(FakeClient(raises=fault)),
        "get_delivery_status",
        {"order_number": "1042"},
        identity=_verified(),
    )
    assert result.ok is False
    assert result.error_class == "auth_expired"


def test_unclassified_client_error_becomes_governed_not_a_raw_raise() -> None:
    result = _call(
        _driver(FakeClient(raises=RuntimeError("socket exploded"))),
        "get_delivery_status",
        {"order_number": "1042"},
        identity=_verified(),
    )
    assert result.ok is False
    # execute_tool converts any ToolDriverError to a governed failure; a raw
    # RuntimeError from the client is wrapped by _fetch_bounded into one first.
    assert result.error_class == "configuration_missing"


# --- deadline: bounds the WHOLE call, not one request (NFR-8, S12 finding) ----


def test_deadline_bounds_the_whole_multi_request_call() -> None:
    # 4 sub-requests × 40ms = 160ms of work under a 60ms budget: a per-REQUEST
    # bound would pass (each 40ms < 60ms); the per-CALL bound must time out.
    slow = FakeClient([RAW_1042], sleep_s=0.04, sub_requests=4)
    start = time.monotonic()
    result = _call(
        _driver(slow, deadline_ms=60),
        "get_delivery_status",
        {"order_number": "1042"},
        identity=_verified(),
    )
    elapsed = time.monotonic() - start
    assert result.ok is False
    assert result.error_class == "vendor_timeout"
    # The turn was released near the deadline, not after the full 160ms of work.
    assert elapsed < 0.15


def test_fast_call_under_the_deadline_succeeds() -> None:
    result = _call(
        _driver(FakeClient([RAW_1042], sleep_s=0.005), deadline_ms=1000),
        "get_delivery_status",
        {"order_number": "1042"},
        identity=_verified(),
    )
    assert result.ok is True


# --- configuration fail-closed (missing token, FR-21) ------------------------


def test_missing_credentials_build_a_driver_that_fails_closed_per_call(monkeypatch) -> None:
    monkeypatch.delenv("EASYROUTES_API_TOKEN", raising=False)
    monkeypatch.delenv("EASYROUTES_CLIENT_ID", raising=False)
    driver = build_easyroutes_driver()  # total — must not raise
    result = _call(
        driver, "get_delivery_status", {"order_number": "1042"}, identity=_verified()
    )
    assert result.ok is False
    assert result.error_class == "configuration_missing"


def test_build_with_credentials_yields_a_live_client_driver(monkeypatch) -> None:
    monkeypatch.setenv("EASYROUTES_API_TOKEN", "tok-123")
    monkeypatch.setenv("EASYROUTES_CLIENT_ID", "client-123")
    driver = build_easyroutes_driver()
    assert driver.kind == "easyroutes"
    assert driver._config_error is None
    assert driver._client is not None


# --- live client body-shape parsing (S26 empty-vs-error trap) ---------------
#
# Unlike the FakeClient tests above (which inject already-parsed records and
# never touch the wire-shape parsing), these exercise the real
# ``_HttpEasyroutesClient.fetch_deliveries`` -- specifically the branch that
# decides whether a 200 body is a recognized-empty result or a fault. That
# decision is the one this fix wave changed; ``urlopen`` is faked at the
# module level so no network runs.


class _FakeHttpResponse:
    """Minimal context-manager stand-in for ``http.client.HTTPResponse``."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _http_client() -> _HttpEasyroutesClient:
    return _HttpEasyroutesClient(
        base="https://example.test/api", token="tok", client_id="cid"
    )


def _patch_urlopen(monkeypatch: pytest.MonkeyPatch, body: Any) -> None:
    payload = json.dumps(body).encode()
    monkeypatch.setattr(
        "toee_hermes.drivers.easyroutes.driver.urllib.request.urlopen",
        lambda *a, **kw: _FakeHttpResponse(payload),
    )


def test_recognized_empty_deliveries_list_is_an_honest_no_delivery(monkeypatch) -> None:
    # A present-but-empty wrapper list is a RECOGNIZED shape -- a genuine
    # 2xx-empty, not a fault. The client must return [], and end-to-end that
    # is the governed "no delivery" policy block, never Tool Unavailable.
    _patch_urlopen(monkeypatch, {"deliveries": []})
    client = _http_client()
    assert client.fetch_deliveries(order_number="1042") == []

    result = _call(
        _driver(client),
        "get_delivery_status",
        {"order_number": "1042"},
        identity=_verified(),
    )
    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_unrecognized_dict_body_fails_closed_not_a_silent_empty(monkeypatch) -> None:
    # A 200 body the parser does not affirmatively recognize as a delivery
    # list (no top-level list, no deliveries/data/results list, no single
    # delivery object) must NOT fall through to `return []` -- that would
    # become a governed "no delivery" the persona narrates to the customer as
    # fact, exactly the QBO `list_customer_invoices`/Composio `successful:
    # true` S26 trap this module's docstring warns about. It must raise and
    # surface as governed unavailable instead.
    #
    # Before the fix: this body reached the old `return []` catch-all and the
    # test below failed (result.ok was True / error_class was "policy_blocked"
    # instead of "configuration_missing"). After the fix it raises.
    _patch_urlopen(monkeypatch, {"unexpected": "shape", "meta": {"page": 1}})
    client = _http_client()
    with pytest.raises(ToolDriverError) as excinfo:
        client.fetch_deliveries(order_number="1042")
    assert excinfo.value.error_class == "configuration_missing"

    result = _call(
        _driver(client),
        "get_delivery_status",
        {"order_number": "1042"},
        identity=_verified(),
    )
    assert result.ok is False
    assert result.error_class == "configuration_missing"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
