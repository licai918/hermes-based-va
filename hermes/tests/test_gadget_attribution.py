"""QboAttribution — the S27 Shopify<->QBO attribution primitive (0.0.4 S27).

The primitive S13 codes against. Both directions must, under the owner's trust rule
(CONFIRMED/AUTO_MATCHED only), FAIL CLOSED on: no mapping, unconfirmed/rejected
status, ambiguity, or a Gadget fault/timeout — never a silent empty success. These
tests drive the primitive against a fake Gadget client (no network); the live wire
shape (:class:`_HttpGadgetClient`) is UNVERIFIED and covered by the S16 probe.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import pytest

from toee_hermes.drivers.gadget import (
    QboAttribution,
    build_qbo_attribution,
    gadget_configured,
)
from toee_hermes.errors import ToolDriverError

VERIFIED = "gid://shopify/Customer/1001"
OTHER = "gid://shopify/Customer/9999"
QBO_ID = "QBO-77"


def _mapping(**over: Any) -> dict[str, Any]:
    base = {
        "id": "m1",
        "qboCustomerId": QBO_ID,
        "shopifyCustomerGid": VERIFIED,
        "status": "CONFIRMED",
        "matchConfidence": 0.9,
        "lockedByUser": False,
    }
    base.update(over)
    return base


class FakeGadgetClient:
    """Returns canned mapping records, or raises to simulate a Gadget fault."""

    def __init__(
        self, records: Optional[list[dict[str, Any]]] = None, *, error: Exception | None = None
    ) -> None:
        self._records = records or []
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def query_customer_mappings(
        self,
        *,
        shopify_customer_gid: Optional[str] = None,
        qbo_customer_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {"shopify_customer_gid": shopify_customer_gid, "qbo_customer_id": qbo_customer_id}
        )
        if self._error is not None:
            raise self._error
        return list(self._records)


def _attr(client: FakeGadgetClient) -> QboAttribution:
    return QboAttribution(client)


# --- forward: verified GID -> QBO customer id --------------------------------


def test_qbo_customer_id_for_confirmed_mapping() -> None:
    attr = _attr(FakeGadgetClient([_mapping()]))
    assert attr.qbo_customer_id_for(VERIFIED) == QBO_ID


def test_qbo_customer_id_for_auto_matched_is_trusted() -> None:
    attr = _attr(FakeGadgetClient([_mapping(status="AUTO_MATCHED")]))
    assert attr.qbo_customer_id_for(VERIFIED) == QBO_ID


def test_qbo_customer_id_for_needs_review_fails_closed() -> None:
    attr = _attr(FakeGadgetClient([_mapping(status="NEEDS_REVIEW")]))
    with pytest.raises(ToolDriverError):
        attr.qbo_customer_id_for(VERIFIED)


def test_qbo_customer_id_for_rejected_fails_closed() -> None:
    attr = _attr(FakeGadgetClient([_mapping(status="REJECTED")]))
    with pytest.raises(ToolDriverError):
        attr.qbo_customer_id_for(VERIFIED)


def test_qbo_customer_id_for_no_mapping_fails_closed() -> None:
    attr = _attr(FakeGadgetClient([]))
    with pytest.raises(ToolDriverError):
        attr.qbo_customer_id_for(VERIFIED)


def test_qbo_customer_id_for_ambiguous_fails_closed() -> None:
    # Two trusted mappings, same preference, different qboCustomerId -> cannot pick.
    attr = _attr(
        FakeGadgetClient(
            [
                _mapping(id="a", qboCustomerId="QBO-A"),
                _mapping(id="b", qboCustomerId="QBO-B"),
            ]
        )
    )
    with pytest.raises(ToolDriverError):
        attr.qbo_customer_id_for(VERIFIED)


def test_qbo_customer_id_for_prefers_locked_over_ambiguous() -> None:
    # lockedByUser breaks the tie: the locked mapping wins, no ambiguity error.
    attr = _attr(
        FakeGadgetClient(
            [
                _mapping(id="a", qboCustomerId="QBO-A", lockedByUser=False),
                _mapping(id="b", qboCustomerId="QBO-B", lockedByUser=True),
            ]
        )
    )
    assert attr.qbo_customer_id_for(VERIFIED) == "QBO-B"


def test_qbo_customer_id_for_gadget_fault_fails_closed() -> None:
    attr = _attr(FakeGadgetClient(error=RuntimeError("gadget 503")))
    with pytest.raises(ToolDriverError):
        attr.qbo_customer_id_for(VERIFIED)


# --- A1 collision guard: many-GID -> one-QBO-id must fail closed on LIST -------


def test_qbo_customer_id_for_fails_closed_on_gid_collision() -> None:
    # The real cross-customer-disclosure scenario: two DIFFERENT trusted Shopify
    # customers both map to the SAME QBO id. Forward-resolving A's QBO id succeeds
    # (both rows agree on it), but listing every invoice billed to that QBO id would
    # hand B's invoices to A. The guard round-trips through the reverse direction and
    # fails closed. FakeGadgetClient returns both rows for BOTH the forward and the
    # reverse query, which is exactly the live collision.
    gid_a = VERIFIED
    gid_b = OTHER
    attr = _attr(
        FakeGadgetClient(
            [
                _mapping(id="a", shopifyCustomerGid=gid_a, status="AUTO_MATCHED"),
                _mapping(id="b", shopifyCustomerGid=gid_b, status="AUTO_MATCHED"),
            ]
        )
    )
    with pytest.raises(ToolDriverError):
        attr.qbo_customer_id_for(gid_a)


def test_qbo_customer_id_for_single_owner_still_lists() -> None:
    # No over-tightening: the normal one-GID-one-QBO-id case still resolves.
    attr = _attr(FakeGadgetClient([_mapping()]))
    assert attr.qbo_customer_id_for(VERIFIED) == QBO_ID


# --- canonical QBO id: representational variants must not deny a legit customer


def test_canonical_qbo_id_matches_app_normalization() -> None:
    from toee_hermes.drivers.gadget import _canonical_qbo_id

    # Mirrors the app's canonicalQboCustomerIdKey: "4902", 4902, " 4902 ", "004902"
    # all collapse to one key so a legit customer is never denied their own invoices.
    assert (
        _canonical_qbo_id("4902")
        == _canonical_qbo_id(4902)
        == _canonical_qbo_id(" 4902 ")
        == _canonical_qbo_id("004902")
        == "4902"
    )
    # Non-numeric ids are preserved (trimmed); empty/None -> None.
    assert _canonical_qbo_id(" QBO-77 ") == "QBO-77"
    assert _canonical_qbo_id("") is None
    assert _canonical_qbo_id(None) is None


def test_qbo_customer_id_for_returns_canonical_id() -> None:
    # A mapping storing the numeric QBO id resolves to its canonical string form.
    attr = _attr(FakeGadgetClient([_mapping(qboCustomerId=4902)]))
    assert attr.qbo_customer_id_for(VERIFIED) == "4902"


# --- reverse: invoice QBO customer -> owned by this GID? ----------------------


def test_invoice_owned_by_true_for_matching_confirmed() -> None:
    attr = _attr(FakeGadgetClient([_mapping()]))
    assert attr.invoice_owned_by(QBO_ID, VERIFIED) is True
    assert attr.__class__ is QboAttribution  # sanity


def test_invoice_owned_by_false_for_other_customer() -> None:
    attr = _attr(FakeGadgetClient([_mapping(shopifyCustomerGid=OTHER)]))
    assert attr.invoice_owned_by(QBO_ID, VERIFIED) is False


def test_invoice_owned_by_unconfirmed_fails_closed() -> None:
    attr = _attr(FakeGadgetClient([_mapping(status="NEEDS_REVIEW")]))
    with pytest.raises(ToolDriverError):
        attr.invoice_owned_by(QBO_ID, VERIFIED)


def test_invoice_owned_by_no_mapping_fails_closed() -> None:
    attr = _attr(FakeGadgetClient([]))
    with pytest.raises(ToolDriverError):
        attr.invoice_owned_by(QBO_ID, VERIFIED)


def test_invoice_owned_by_ambiguous_fails_closed() -> None:
    attr = _attr(
        FakeGadgetClient(
            [
                _mapping(id="a", shopifyCustomerGid=VERIFIED),
                _mapping(id="b", shopifyCustomerGid=OTHER),
            ]
        )
    )
    with pytest.raises(ToolDriverError):
        attr.invoice_owned_by(QBO_ID, VERIFIED)


def test_invoice_owned_by_tolerates_bare_numeric_gid() -> None:
    # A mapping row storing the short Shopify id still joins to the canonical gid.
    attr = _attr(FakeGadgetClient([_mapping(shopifyCustomerGid="1001")]))
    assert attr.invoice_owned_by(QBO_ID, VERIFIED) is True


# --- deadline + config -------------------------------------------------------


def test_query_is_bounded_by_the_per_call_deadline() -> None:
    class SlowClient:
        def query_customer_mappings(self, **_: Any) -> list[dict[str, Any]]:
            time.sleep(0.5)
            return []

    attr = QboAttribution(SlowClient(), deadline_ms=20)
    with pytest.raises(ToolDriverError) as excinfo:
        attr.qbo_customer_id_for(VERIFIED)
    assert excinfo.value.error_class == "vendor_timeout"


def test_unconfigured_attributor_fails_closed() -> None:
    attr = build_qbo_attribution()  # no GADGET_API_KEY in the test env
    with pytest.raises(ToolDriverError) as excinfo:
        attr.qbo_customer_id_for(VERIFIED)
    assert excinfo.value.error_class == "configuration_missing"


def test_gadget_configured_reflects_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GADGET_API_KEY", raising=False)
    assert gadget_configured() is False
    monkeypatch.setenv("GADGET_API_KEY", "gsk-test")
    assert gadget_configured() is True


def test_build_is_total_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GADGET_API_KEY", raising=False)
    # Must not raise at build time (a missing owner-blocked key must not block boot).
    attr = build_qbo_attribution()
    assert isinstance(attr, QboAttribution)


def test_records_envelope_fails_closed_on_graphql_errors() -> None:
    from toee_hermes.drivers.gadget import _records_from_envelope

    with pytest.raises(ToolDriverError):
        _records_from_envelope({"errors": [{"message": "denied"}]})


def test_records_envelope_reads_connection_nodes() -> None:
    from toee_hermes.drivers.gadget import _records_from_envelope

    parsed = {
        "data": {"qboCustomerMappings": {"edges": [{"node": _mapping()}]}}
    }
    assert _records_from_envelope(parsed) == [_mapping()]


def test_records_envelope_empty_connection_is_clean_empty() -> None:
    from toee_hermes.drivers.gadget import _records_from_envelope

    assert _records_from_envelope({"data": {"qboCustomerMappings": {"edges": []}}}) == []


def test_records_envelope_unrecognized_shape_fails_closed() -> None:
    from toee_hermes.drivers.gadget import _records_from_envelope

    with pytest.raises(ToolDriverError):
        _records_from_envelope({"data": {"somethingElse": {}}})
