"""Mock driver + toee_identity_lookup handlers (ports mock/identity.ts).

Resolves Ingress Phone Match / Email Sender Match to Session Identity Snapshot
outcomes (ADR-0043, ADR-0060) and reports Customer Email Link readiness for QBO
accounting reads. Exercised through `execute_tool` so the governed boundary is
covered end-to-end.
"""

from toee_hermes.drivers.mock import IdentityMockData, MockDriver, create_identity_mock_handlers
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext


def _driver() -> MockDriver:
    return MockDriver(create_identity_mock_handlers())


def _isolated_driver() -> MockDriver:
    # Its own IdentityMockData rather than the process-wide identity_baseline_data
    # singleton, so link_identity's in-place mutation can't leak into other tests
    # sharing the default baseline (0.0.3 S05).
    return MockDriver(create_identity_mock_handlers(IdentityMockData()))


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext(profile="customer_service_external")


def _call(action: str, params: dict, driver: MockDriver | None = None):
    return execute_tool(
        tool="toee_identity_lookup",
        action=action,
        params=params,
        context=_ctx(),
        driver=driver or _driver(),
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


# --- link_identity (0.0.3 S05, FR-13) ---------------------------------------


def test_link_identity_makes_a_previously_unmatched_phone_verified() -> None:
    driver = _isolated_driver()
    before = _call("match_phone", {"phone": "+15551230000"}, driver)
    assert before.data["outcome"] == "unmatched_caller"

    linked = _call(
        "link_identity",
        {
            "channel_identity": "+15551230000",
            "shopify_customer_id": "gid://shopify/Customer/9001",
            "company_name": "Hot Wheel Tire Service Inc.",
        },
        driver,
    )
    assert linked.ok is True
    assert linked.data == {
        "outcome": "linked",
        "channel": "sms",
        "channel_identity": "+15551230000",
        "shopify_customer_id": "gid://shopify/Customer/9001",
    }

    after = _call("match_phone", {"phone": "+15551230000"}, driver)
    assert after.data["outcome"] == "verified_customer"
    assert after.data["shopify_customer_id"] == "gid://shopify/Customer/9001"
    assert after.data["company_name"] == "Hot Wheel Tire Service Inc."


def test_link_identity_supports_the_email_channel() -> None:
    driver = _isolated_driver()
    linked = _call(
        "link_identity",
        {
            "channel": "email",
            "channel_identity": "new@example.com",
            "shopify_customer_id": "gid://shopify/Customer/9002",
        },
        driver,
    )
    assert linked.data["channel"] == "email"

    after = _call("match_email_sender", {"from_address": "new@example.com"}, driver)
    assert after.data["outcome"] == "verified_customer"
    assert after.data["shopify_customer_id"] == "gid://shopify/Customer/9002"


def test_link_identity_requires_channel_identity() -> None:
    result = _call(
        "link_identity",
        {"shopify_customer_id": "gid://shopify/Customer/9001"},
        _isolated_driver(),
    )
    assert result.ok is False
    assert result.error_class == "unexpected_error"


def test_link_identity_requires_shopify_customer_id() -> None:
    result = _call(
        "link_identity", {"channel_identity": "+15551230000"}, _isolated_driver()
    )
    assert result.ok is False
    assert result.error_class == "unexpected_error"


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
