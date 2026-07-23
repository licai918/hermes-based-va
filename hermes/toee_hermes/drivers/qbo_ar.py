"""Shared AR-summary aggregation for ``toee_qbo_read.get_ar_summary`` (0.0.4 S13, FR-19).

The live (Composio) and mock QBO drivers MUST produce a byte-identical AR summary
shape so dev/eval and production agree. Rather than derive the summary from
``QUICKBOOKS_GET_AGED_RECEIVABLES_REPORT`` -- an ALL-customer aggregate that cannot
be scoped to one customer without misattributing another customer's balance (the
exact disclosure the S27 attribution primitive exists to prevent) -- both drivers
compute it from the verified customer's OWN, ownership-scoped invoices (the S27
per-customer list path) and call this ONE aggregator. One definition, no drift.

"open" = a positive outstanding balance. A fully-paid invoice (balance 0) is not
receivable, so it is not counted. This is the judgement the slice makes explicit:
count + total are over invoices with ``balance > 0`` only.

ponytail: v1 contract is count + total, no due-date aging buckets. Add 30/60/90
buckets HERE if the persona ever reports ages -- that needs the invoice ``DueDate``
field, an UNVERIFIED live probe (S27's list path extracts only ``Balance`` today).
"""

from __future__ import annotations

from typing import Any


def _balance(invoice: dict[str, Any]) -> float:
    value = invoice.get("balance")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def ar_summary(
    shopify_customer_id: str | None, owned_invoices: list[dict[str, Any]]
) -> dict[str, Any]:
    """Aggregate a verified customer's OWN invoices into the v1 AR summary shape.

    ``owned_invoices`` are already ownership-scoped by the caller (mock: direct
    ``shopify_customer_id`` match; live: through the S27 Gadget attribution
    primitive). An empty list from a POSITIVELY attributed customer is an honest
    "$0 owing". The empty-vs-error rule lives in the CALLER: attribution or backend
    FAILURE must raise BEFORE reaching here, so a fabricated/empty "$0" is never
    emitted on error -- only a genuinely-zero, positively-attributed customer gets 0.
    """
    open_invoices = [inv for inv in owned_invoices if _balance(inv) > 0]
    return {
        "shopify_customer_id": shopify_customer_id,
        "open_invoice_count": len(open_invoices),
        "total_balance": sum(_balance(inv) for inv in open_invoices),
    }


if __name__ == "__main__":  # ponytail self-check: the open-filter + shape invariant
    _me = "gid://shopify/Customer/1001"
    assert ar_summary(_me, []) == {
        "shopify_customer_id": _me,
        "open_invoice_count": 0,
        "total_balance": 0,
    }, "positively-attributed empty must be an honest $0"
    _mixed = [{"balance": 1250.0}, {"balance": 0}, {"balance": 42}]
    _out = ar_summary(_me, _mixed)
    assert _out["open_invoice_count"] == 2, "paid (balance 0) invoice must not count as open"
    assert _out["total_balance"] == 1292.0, _out
    print("qbo_ar self-check ok")
