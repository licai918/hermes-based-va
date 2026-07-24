"""External Customer Service Profile Tool Gate (ADR-0033, ADR-0034, ADR-0062).

Policy enforcement is layered, not skill-only (ADR-0033): the Profile Tool
Allowlist decides *which* tools exist, and a Tool Gate decides whether a specific
request is allowed before the driver runs. This gate owns the Customer Email Link
check for QBO accounting reads: ``toee_qbo_read`` requires a verified customer
whose matched Shopify Customer is linked to a QBO Customer. On a missing or failed
link the gate denies with ``policy_blocked`` so the turn surfaces a governed
failure instead of leaking partial accounting facts (ADR-0020, ADR-0062).

The link status is injected (mock-first): the Launch Eval harness builds the gate
from the scenario's merged ``qbo.email_links``; a live deployment will source the
same readiness from ``toee_identity_lookup.get_email_link_status``.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ..tool_gate import GateDecision, ToolExecutionContext, ToolGate

QBO_READ_TOOL = "toee_qbo_read"
LINKED = "linked"


def _verified_customer_id(identity: Any) -> Optional[str]:
    """Verified customer's Shopify id from the Session Identity Snapshot, else None."""
    if isinstance(identity, Mapping) and identity.get("outcome") == "verified_customer":
        customer_id = identity.get("shopify_customer_id")
        if isinstance(customer_id, str) and customer_id:
            return customer_id
    return None


def create_external_profile_gate(*, email_links: Mapping[str, str]) -> ToolGate:
    """Build the External profile gate bound to a Customer Email Link map.

    ``email_links`` maps a matched Shopify Customer id to ``"linked"`` /
    ``"unlinked"``; any value other than ``"linked"`` (or a missing key) blocks the
    accounting read.
    """
    links = dict(email_links)

    def gate(request: Any, context: ToolExecutionContext) -> GateDecision:
        # DELIVERY verified-vs-public asymmetry (0.0.4 S32, role-asymmetry-as-intent,
        # mirrors the S15 note): the External gate ALLOWS the whole toee_delivery_promise
        # tool for every caller — including an unmatched/unverified prospect — on purpose.
        # get_delivery_quote (Tier 3b) is a PUBLIC area-level estimate (postal + sku, NO
        # customer id, no PII), so a prospect must be able to call it. The two account
        # actions (get_order_delivery / get_product_promise) are NOT weakened by this: the
        # DRIVER enforces verified-only on them (fails closed for an unverified caller
        # before any HTTP call, and sends the verified snapshot id, never a model-supplied
        # one). The per-action verified requirement lives at that single enforcement point,
        # not here, so this gate intentionally does not special-case delivery.
        if request.tool != QBO_READ_TOOL:
            return GateDecision(allow=True)

        customer_id = _verified_customer_id(context.identity)
        if customer_id is None:
            return GateDecision(
                allow=False,
                error_class="policy_blocked",
                message="QBO read requires a verified customer.",
            )
        if links.get(customer_id) != LINKED:
            return GateDecision(
                allow=False,
                error_class="policy_blocked",
                message="QBO read requires a successful customer email link.",
            )
        return GateDecision(allow=True)

    return gate
