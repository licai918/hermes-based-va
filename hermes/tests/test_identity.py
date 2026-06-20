"""Mock driver + toee_identity_lookup handlers (ports mock/identity.ts).

Resolves Ingress Phone Match / Email Sender Match to Session Identity Snapshot
outcomes (ADR-0043, ADR-0060) and reports Customer Email Link readiness for QBO
accounting reads. Exercised through `execute_tool` so the governed boundary is
covered end-to-end.
"""

from toee_hermes.drivers.mock import MockDriver, create_identity_mock_handlers
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext


def _driver() -> MockDriver:
    return MockDriver(create_identity_mock_handlers())


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext(profile="customer_service_external")


def _call(action: str, params: dict):
    return execute_tool(
        tool="toee_identity_lookup",
        action=action,
        params=params,
        context=_ctx(),
        driver=_driver(),
    )


def test_match_phone_verified_customer() -> None:
    result = _call("match_phone", {"phone": "+14165550101"})

    assert result.ok is True
    assert result.data["outcome"] == "verified_customer"
    assert result.data["shopify_customer_id"] == "gid://shopify/Customer/1001"
    assert result.data["company_name"] == "Acme Fleet"


def test_match_phone_unmatched_caller_when_absent() -> None:
    result = _call("match_phone", {"phone": "+19999999999"})

    assert result.ok is True
    assert result.data == {"outcome": "unmatched_caller"}


def test_match_phone_ambiguous_returns_candidate_ids() -> None:
    result = _call("match_phone", {"phone": "+14165550222"})

    assert result.data["outcome"] == "ambiguous_phone_match"
    assert result.data["shopify_customer_ids"] == [
        "gid://shopify/Customer/2001",
        "gid://shopify/Customer/2002",
    ]


def test_match_phone_passes_resolved_at_through_when_supplied() -> None:
    result = _call(
        "match_phone", {"phone": "+14165550101", "resolved_at": "2026-01-01T00:00:00Z"}
    )

    assert result.data["resolved_at"] == "2026-01-01T00:00:00Z"


def test_match_phone_default_output_is_deterministic_without_resolved_at() -> None:
    result = _call("match_phone", {"phone": "+19999999999"})

    assert "resolved_at" not in result.data


def test_match_email_sender_verified_customer() -> None:
    result = _call("match_email_sender", {"from_address": "accounts@acme-fleet.example"})

    assert result.data["outcome"] == "verified_customer"
    assert result.data["shopify_customer_id"] == "gid://shopify/Customer/1001"


def test_get_email_link_status_linked_by_customer_id() -> None:
    result = _call(
        "get_email_link_status", {"shopify_customer_id": "gid://shopify/Customer/1001"}
    )

    assert result.data == {"status": "linked"}


def test_get_email_link_status_defaults_to_unlinked() -> None:
    result = _call("get_email_link_status", {"email": "stranger@example.com"})

    assert result.data == {"status": "unlinked"}


def test_missing_mock_handler_is_governed_configuration_missing() -> None:
    # The identity-only registry has no toee_shopify_read handler; the driver must
    # surface a governed failure, not raise.
    result = execute_tool(
        tool="toee_shopify_read",
        action="get_order",
        params={"order_id": "1"},
        context=_ctx(),
        driver=_driver(),
    )

    assert result.ok is False
    assert result.error_class == "configuration_missing"
