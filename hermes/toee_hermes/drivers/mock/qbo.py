"""Mock handlers for ``toee_qbo_read`` (ports mock/qbo.ts, ADR-0062).

Serves the v1 accounting reads ``get_invoice``, ``list_customer_invoices`` and
``get_ar_summary``. Faithful to the TS ``(params, context)`` handlers: ownership
is sourced from the Session Identity Snapshot at ``context.identity`` (ADR-0043),
never from ``params``. The owner is the verified customer's ``shopify_customer_id``
(present only when ``outcome == "verified_customer"``); an unmatched (``None``) or
ambiguous identity owns no invoices, so identity-scoped reads return nothing /
refuse to disclose another customer's accounting facts (ADR-0020).

The Customer Email Link gate remains a Tool-Gate concern (ADR-0033, ADR-0062) and
is intentionally NOT enforced here; ``email_links`` is retained only for base.yaml
fixture parity so the Tool Gate can read it. Outputs are deterministic.

Data is injectable so the Launch Eval fixture loader can override the baseline
seeded from ``eval/mocks/base.yaml`` (ADR-0137).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ...errors import ToolDriverError
from ..qbo_ar import ar_summary
from .driver import MockHandlerRegistry

if TYPE_CHECKING:
    from ...tool_gate import ToolExecutionContext


@dataclass(frozen=True)
class QboMockData:
    # Customer Email Link status keyed by matched Shopify Customer id. Read by the
    # Tool Gate, not the mock; kept here for base.yaml fixture parity (ADR-0062).
    email_links: dict[str, str] = field(default_factory=dict)
    # Invoices with snake_case keys: invoice_number, shopify_customer_id,
    # customer_email, balance.
    invoices: list[dict[str, Any]] = field(default_factory=list)


# Seeded from eval/mocks/base.yaml. The base file keys the email link by the
# ``verified_customer_a`` identity preset, whose shopify_customer_id is
# gid://shopify/Customer/1001, so the link and the invoice are keyed by that id.
qbo_baseline_data = QboMockData(
    email_links={"gid://shopify/Customer/1001": "linked"},
    invoices=[
        {
            "invoice_number": "INV-9001",
            "shopify_customer_id": "gid://shopify/Customer/1001",
            "customer_email": "accounts@acme-fleet.example",
            "balance": 1250.0,
        }
    ],
)


def _read_string(params: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = params.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _owner_id(context: "ToolExecutionContext") -> str | None:
    """Verified customer's Shopify id from the Session Identity Snapshot, else None.

    Unmatched (``identity is None``) and ambiguous matches carry no single
    ``shopify_customer_id`` and therefore own no invoices.
    """
    identity = context.identity
    if isinstance(identity, dict) and identity.get("outcome") == "verified_customer":
        customer_id = identity.get("shopify_customer_id")
        if isinstance(customer_id, str) and customer_id:
            return customer_id
    return None


def _owned_by(invoice: dict[str, Any], customer_id: str | None) -> bool:
    # Require an exact owner match; a missing owner (None) owns no invoice.
    return customer_id is not None and invoice.get("shopify_customer_id") == customer_id


def _get_invoice(
    data: QboMockData, params: dict[str, Any], context: "ToolExecutionContext"
) -> dict[str, Any]:
    invoice_number = _read_string(params, "invoice_number", "invoiceNumber")
    customer_id = _owner_id(context)
    for invoice in data.invoices:
        if invoice.get("invoice_number") == invoice_number and _owned_by(
            invoice, customer_id
        ):
            return dict(invoice)
    raise ToolDriverError(
        "policy_blocked",
        f"No invoice {invoice_number or '<missing>'} owned by the verified customer.",
    )


def _list_customer_invoices(
    data: QboMockData, params: dict[str, Any], context: "ToolExecutionContext"
) -> list[dict[str, Any]]:
    customer_id = _owner_id(context)
    return [
        dict(invoice) for invoice in data.invoices if _owned_by(invoice, customer_id)
    ]


def _get_ar_summary(
    data: QboMockData, params: dict[str, Any], context: "ToolExecutionContext"
) -> dict[str, Any]:
    # Same shape and "open = balance > 0" semantics as the live Composio path, via
    # the shared aggregator (0.0.4 S13). A None owner owns nothing -> honest $0.
    customer_id = _owner_id(context)
    owned = [invoice for invoice in data.invoices if _owned_by(invoice, customer_id)]
    return ar_summary(customer_id, owned)


def create_qbo_mock_handlers(
    data: QboMockData = qbo_baseline_data,
) -> MockHandlerRegistry:
    """Build the registry fragment bound to a specific data set.

    The Launch Eval fixture loader passes per-scenario data; the default uses the
    base.yaml baseline.
    """
    return {
        "toee_qbo_read": {
            "get_invoice": lambda params, context: _get_invoice(data, params, context),
            "list_customer_invoices": lambda params, context: _list_customer_invoices(
                data, params, context
            ),
            "get_ar_summary": lambda params, context: _get_ar_summary(
                data, params, context
            ),
        }
    }
