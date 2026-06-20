"""Mock toee_qbo_read handlers (ports mock/qbo.ts, ADR-0062).

The v1 accounting reads (get_invoice, list_customer_invoices, get_ar_summary)
are exercised end-to-end through ``execute_tool`` so the governed boundary is
covered. Ownership comes from the Session Identity Snapshot at ``context.identity``
(ADR-0043), faithful to the TS ``(params, context)`` handlers -- the verified
customer's ``shopify_customer_id`` scopes the reads, an unmatched (``None``)
identity owns nothing. The Customer Email Link gate stays a Tool-Gate concern
(ADR-0033, ADR-0062) and is not exercised here.
"""

from toee_hermes.drivers.mock.driver import MockDriver
from toee_hermes.drivers.mock.qbo import (
    QboMockData,
    create_qbo_mock_handlers,
    qbo_baseline_data,
)
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

VERIFIED_CUSTOMER_ID = "gid://shopify/Customer/1001"
OTHER_CUSTOMER_ID = "gid://shopify/Customer/9999"

VERIFIED_IDENTITY = {
    "outcome": "verified_customer",
    "shopify_customer_id": VERIFIED_CUSTOMER_ID,
    "company_name": "Acme Fleet",
}
OTHER_IDENTITY = {
    "outcome": "verified_customer",
    "shopify_customer_id": OTHER_CUSTOMER_ID,
    "company_name": "Other Co",
}


def _call(
    action: str,
    params: dict | None = None,
    *,
    identity: dict | None,
    data: QboMockData = qbo_baseline_data,
):
    return execute_tool(
        tool="toee_qbo_read",
        action=action,
        params=params or {},
        context=ToolExecutionContext(
            profile="customer_service_external", identity=identity
        ),
        driver=MockDriver(create_qbo_mock_handlers(data)),
    )


# --- get_invoice -----------------------------------------------------------


def test_get_invoice_returns_owned_invoice() -> None:
    result = _call(
        "get_invoice", {"invoice_number": "INV-9001"}, identity=VERIFIED_IDENTITY
    )

    assert result.ok is True
    assert result.data == {
        "invoice_number": "INV-9001",
        "shopify_customer_id": VERIFIED_CUSTOMER_ID,
        "customer_email": "accounts@acme-fleet.example",
        "balance": 1250.0,
    }


def test_get_invoice_output_keys_are_snake_case() -> None:
    result = _call(
        "get_invoice", {"invoice_number": "INV-9001"}, identity=VERIFIED_IDENTITY
    )

    assert set(result.data.keys()) == {
        "invoice_number",
        "shopify_customer_id",
        "customer_email",
        "balance",
    }
    assert "invoiceNumber" not in result.data
    assert "shopifyCustomerId" not in result.data


def test_get_invoice_unknown_number_is_governed_failure() -> None:
    # "Not found" path: never fabricate an invoice (ADR-0020).
    result = _call(
        "get_invoice", {"invoice_number": "INV-0000"}, identity=VERIFIED_IDENTITY
    )

    assert result.ok is False
    assert result.error_class == "policy_blocked"
    assert result.data is None


def test_get_invoice_unmatched_caller_is_governed_failure() -> None:
    # No verified owner (identity=None) -> the invoice is not owned -> blocked.
    result = _call("get_invoice", {"invoice_number": "INV-9001"}, identity=None)

    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_get_invoice_other_verified_owner_is_governed_failure() -> None:
    # A different verified customer must not read an invoice they do not own.
    result = _call(
        "get_invoice", {"invoice_number": "INV-9001"}, identity=OTHER_IDENTITY
    )

    assert result.ok is False
    assert result.error_class == "policy_blocked"


# --- list_customer_invoices ------------------------------------------------


def test_list_customer_invoices_returns_owned() -> None:
    result = _call("list_customer_invoices", identity=VERIFIED_IDENTITY)

    assert result.ok is True
    assert result.data == [
        {
            "invoice_number": "INV-9001",
            "shopify_customer_id": VERIFIED_CUSTOMER_ID,
            "customer_email": "accounts@acme-fleet.example",
            "balance": 1250.0,
        }
    ]


def test_list_customer_invoices_empty_for_other_owner() -> None:
    result = _call("list_customer_invoices", identity=OTHER_IDENTITY)

    assert result.ok is True
    assert result.data == []


# --- get_ar_summary --------------------------------------------------------


def test_get_ar_summary_returns_totals() -> None:
    result = _call("get_ar_summary", identity=VERIFIED_IDENTITY)

    assert result.ok is True
    assert result.data == {
        "shopify_customer_id": VERIFIED_CUSTOMER_ID,
        "open_invoice_count": 1,
        "total_balance": 1250.0,
    }


def test_get_ar_summary_zero_for_other_owner() -> None:
    result = _call("get_ar_summary", identity=OTHER_IDENTITY)

    assert result.ok is True
    assert result.data["open_invoice_count"] == 0
    assert result.data["total_balance"] == 0


def test_get_ar_summary_is_deterministic_across_calls() -> None:
    first = _call("get_ar_summary", identity=VERIFIED_IDENTITY)
    second = _call("get_ar_summary", identity=VERIFIED_IDENTITY)

    assert first.data == second.data


# --- injectable data (Launch Eval fixture loader, ADR-0137) ----------------


def test_create_qbo_mock_handlers_accepts_injected_data() -> None:
    injected = QboMockData(
        email_links={OTHER_CUSTOMER_ID: "linked"},
        invoices=[
            {
                "invoice_number": "INV-7777",
                "shopify_customer_id": OTHER_CUSTOMER_ID,
                "customer_email": "ops@other.example",
                "balance": 42.5,
            }
        ],
    )

    result = _call(
        "get_invoice",
        {"invoice_number": "INV-7777"},
        identity=OTHER_IDENTITY,
        data=injected,
    )

    assert result.ok is True
    assert result.data["invoice_number"] == "INV-7777"
    assert result.data["balance"] == 42.5
