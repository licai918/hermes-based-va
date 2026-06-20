"""Mock handlers for ``toee_square_payment_link`` (ports mock/square.ts, ADR-0066).

``send_payment_link`` requires a Verified Customer and must stay on the current
verified Textline thread (ADR-0022); the thread is modeled here by a required,
non-empty conversation id. A request to redirect to a new contact (eval scenario
05 turn 2) is refused so the agent opens a Follow-up Case instead. Outputs are
deterministic — the link is derived from the resolved payable, with no external
Square call.

Handlers receive ``(params, context)`` (faithful to the TS handlers). The Session
Identity Snapshot lives at ``context.identity`` (ADR-0043): ``None`` for an
unmatched caller, otherwise a dict carrying ``outcome`` and, when verified, the
owning ``shopify_customer_id``. Data is injectable so the Launch Eval fixture
loader can override the baseline seeded from ``eval/mocks/base.yaml`` (ADR-0137).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ...errors import ToolDriverError
from .driver import MockHandlerRegistry

if TYPE_CHECKING:
    from ...tool_gate import ToolExecutionContext


@dataclass(frozen=True)
class SquarePayable:
    invoice_number: str
    shopify_customer_id: str
    amount: float


@dataclass(frozen=True)
class SquareMockData:
    payment_link_base_url: str
    payables: tuple[SquarePayable, ...] = ()


# Seeded to match the QBO invoice in eval/mocks/base.yaml (INV-9001, balance
# 1250.0, owned by gid://shopify/Customer/1001) so the payment-link amount lines
# up with the open invoice used in eval scenario 05.
square_baseline_data = SquareMockData(
    payment_link_base_url="https://pay.toee.example/square",
    payables=(
        SquarePayable(
            invoice_number="INV-9001",
            shopify_customer_id="gid://shopify/Customer/1001",
            amount=1250.0,
        ),
    ),
)


def _read_string(params: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = params.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _require_verified_customer_id(context: ToolExecutionContext) -> str:
    """Payment links are only ever sent to a Verified Customer (ADR-0066).

    Unmatched and ambiguous sessions never receive a link.
    """
    identity = context.identity
    if not isinstance(identity, dict) or identity.get("outcome") != "verified_customer":
        raise ToolDriverError(
            "policy_blocked",
            "Payment link requires a verified customer.",
        )
    customer_id = identity.get("shopify_customer_id")
    if not isinstance(customer_id, str) or not customer_id:
        raise ToolDriverError(
            "policy_blocked",
            "Verified customer session is missing a Shopify customer id.",
        )
    return customer_id


def _send_payment_link(
    data: SquareMockData, params: dict[str, Any], context: ToolExecutionContext
) -> dict[str, Any]:
    customer_id = _require_verified_customer_id(context)

    # Same-thread gate (ADR-0022): the link is delivered only in the current
    # authenticated Textline thread, modeled by a required conversation id.
    conversation_id = _read_string(params, "conversation_id", "conversationId")
    if conversation_id is None or not conversation_id.strip():
        raise ToolDriverError(
            "policy_blocked",
            "Payment link must be sent in the current verified Textline thread.",
        )

    # A new contact supplied in the message body never changes the send target
    # (ADR-0022 / scenario 05 turn 2); the agent opens a Follow-up Case.
    recipient = _read_string(params, "recipient")
    if recipient is not None and recipient.strip():
        raise ToolDriverError(
            "policy_blocked",
            "Payment link cannot be redirected to an alternate recipient; "
            "create a follow-up case instead.",
        )

    invoice_number = _read_string(params, "invoice_number", "invoiceNumber")
    payable = next(
        (
            candidate
            for candidate in data.payables
            if candidate.invoice_number == invoice_number
            and candidate.shopify_customer_id == customer_id
        ),
        None,
    )
    if payable is None:
        raise ToolDriverError(
            "policy_blocked",
            f"No payable {invoice_number or '<missing>'} owned by the verified customer.",
        )

    return {
        "payment_link_url": f"{data.payment_link_base_url}/{payable.invoice_number}",
        "conversation_id": conversation_id,
        "amount": payable.amount,
    }


def create_square_mock_handlers(
    data: SquareMockData = square_baseline_data,
) -> MockHandlerRegistry:
    """Build the registry fragment bound to a specific data set.

    The Launch Eval fixture loader passes per-scenario data; the default uses the
    base.yaml baseline.
    """
    return {
        "toee_square_payment_link": {
            "send_payment_link": lambda params, context: _send_payment_link(
                data, params, context
            ),
        }
    }
