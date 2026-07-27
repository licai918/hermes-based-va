"""toee_square_payment_link mock handlers (ports mock/square.test.ts).

``send_payment_link`` requires a Verified Customer (Session Identity Snapshot,
ADR-0043) and must stay on the current verified SMS thread (ADR-0022),
modeled by a required, non-empty conversation id. A new contact supplied in the
message body never redirects the link (eval scenario 05 turn 2); the agent opens
a Follow-up Case instead. Exercised through ``execute_tool`` so the governed
boundary is covered end-to-end, and outputs are asserted to be deterministic.
"""

from toee_hermes.drivers.mock.driver import MockDriver
from toee_hermes.drivers.mock.square import create_square_mock_handlers
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

VERIFIED_CUSTOMER_ID = "gid://shopify/Customer/1001"
OTHER_CUSTOMER_ID = "gid://shopify/Customer/9999"
CONVERSATION_ID = "sms:conv_abc123"


def _driver() -> MockDriver:
    return MockDriver(create_square_mock_handlers())


def _ctx(identity: object | None) -> ToolExecutionContext:
    return ToolExecutionContext(profile="customer_service_external", identity=identity)


def _verified_ctx() -> ToolExecutionContext:
    return _ctx(
        {"outcome": "verified_customer", "shopify_customer_id": VERIFIED_CUSTOMER_ID}
    )


def _unmatched_ctx() -> ToolExecutionContext:
    return _ctx({"outcome": "unmatched_caller"})


def _other_owner_ctx() -> ToolExecutionContext:
    return _ctx(
        {"outcome": "verified_customer", "shopify_customer_id": OTHER_CUSTOMER_ID}
    )


def _send(params: dict, context: ToolExecutionContext):
    return execute_tool(
        tool="toee_square_payment_link",
        action="send_payment_link",
        params=params,
        context=context,
        driver=_driver(),
    )


def test_sends_deterministic_link_for_verified_customer_same_thread() -> None:
    result = _send(
        {"invoice_number": "INV-9001", "conversation_id": CONVERSATION_ID},
        _verified_ctx(),
    )

    assert result.ok is True
    assert result.data["conversation_id"] == CONVERSATION_ID
    assert result.data["amount"] == 1250.0
    assert result.data["payment_link_url"] == "https://pay.toee.example/square/INV-9001"


def test_link_is_deterministic_across_calls() -> None:
    params = {"invoice_number": "INV-9001", "conversation_id": CONVERSATION_ID}
    first = _send(dict(params), _verified_ctx())
    second = _send(dict(params), _verified_ctx())

    assert first.ok is True
    assert second.ok is True
    assert first.data == second.data


def test_blocks_when_no_conversation_id() -> None:
    result = _send({"invoice_number": "INV-9001"}, _verified_ctx())

    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_blocks_when_conversation_id_empty() -> None:
    result = _send(
        {"invoice_number": "INV-9001", "conversation_id": ""}, _verified_ctx()
    )

    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_blocks_when_conversation_id_blank() -> None:
    result = _send(
        {"invoice_number": "INV-9001", "conversation_id": "   "}, _verified_ctx()
    )

    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_blocks_unmatched_caller_even_with_conversation_id() -> None:
    result = _send(
        {"invoice_number": "INV-9001", "conversation_id": CONVERSATION_ID},
        _unmatched_ctx(),
    )

    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_blocks_when_identity_missing() -> None:
    result = _send(
        {"invoice_number": "INV-9001", "conversation_id": CONVERSATION_ID}, _ctx(None)
    )

    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_blocks_redirect_to_alternate_recipient() -> None:
    result = _send(
        {
            "invoice_number": "INV-9001",
            "conversation_id": CONVERSATION_ID,
            "recipient": "+14165550199",
        },
        _verified_ctx(),
    )

    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_blocks_when_no_pre_created_link_exists() -> None:
    # 0.0.4 S26 retrieve semantics: links are created ahead of time in the Square
    # console, so an invoice with no link has nothing to send. The mock must refuse
    # rather than mint a URL — minting one is exactly the create behavior the owner
    # decision removed, and it would let dev pass where production has nothing.
    result = _send(
        {"invoice_number": "INV-NO-LINK", "conversation_id": CONVERSATION_ID},
        _verified_ctx(),
    )

    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_blocks_payable_not_owned_by_verified_customer() -> None:
    result = _send(
        {"invoice_number": "INV-9001", "conversation_id": CONVERSATION_ID},
        _other_owner_ctx(),
    )

    assert result.ok is False
    assert result.error_class == "policy_blocked"
