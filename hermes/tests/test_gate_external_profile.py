"""Tests for the External Customer Service Profile Tool Gate (ADR-0033, ADR-0062).

The QBO Customer Email Link gate is a Tool-Gate concern, not a mock concern: the
qbo mock serves data and the gate decides whether an accounting read is allowed.
Every ``toee_qbo_read`` action requires a verified customer whose Shopify Customer
is linked to a QBO Customer; otherwise the gate denies with ``policy_blocked``
rather than letting partial accounting facts leak (ADR-0020).
"""

from __future__ import annotations

from toee_hermes.execute import ToolRequest
from toee_hermes.gates import create_external_profile_gate
from toee_hermes.tool_gate import ToolExecutionContext

EXTERNAL = "customer_service_external"
VERIFIED = {
    "outcome": "verified_customer",
    "shopify_customer_id": "gid://shopify/Customer/1001",
}


def _ctx(identity: object) -> ToolExecutionContext:
    return ToolExecutionContext(profile=EXTERNAL, identity=identity)


def test_allows_qbo_read_when_verified_customer_email_link_is_linked() -> None:
    gate = create_external_profile_gate(
        email_links={"gid://shopify/Customer/1001": "linked"}
    )
    decision = gate(
        ToolRequest(tool="toee_qbo_read", action="get_invoice"), _ctx(VERIFIED)
    )
    assert decision.allow is True


def test_blocks_qbo_read_when_email_link_is_unlinked() -> None:
    gate = create_external_profile_gate(
        email_links={"gid://shopify/Customer/1001": "unlinked"}
    )
    decision = gate(
        ToolRequest(tool="toee_qbo_read", action="get_invoice"), _ctx(VERIFIED)
    )
    assert decision.allow is False
    assert decision.error_class == "policy_blocked"


def test_blocks_qbo_read_when_customer_id_absent_from_email_links() -> None:
    # A verified customer with no email-link entry is treated as not linked.
    gate = create_external_profile_gate(email_links={})
    decision = gate(
        ToolRequest(tool="toee_qbo_read", action="get_ar_summary"), _ctx(VERIFIED)
    )
    assert decision.allow is False
    assert decision.error_class == "policy_blocked"


def test_blocks_qbo_read_for_unmatched_identity() -> None:
    # No verified customer -> no email link is possible -> policy_blocked.
    gate = create_external_profile_gate(
        email_links={"gid://shopify/Customer/1001": "linked"}
    )
    decision = gate(
        ToolRequest(tool="toee_qbo_read", action="get_invoice"),
        _ctx({"outcome": "unmatched_caller"}),
    )
    assert decision.allow is False
    assert decision.error_class == "policy_blocked"


def test_blocks_qbo_read_when_identity_missing() -> None:
    gate = create_external_profile_gate(
        email_links={"gid://shopify/Customer/1001": "linked"}
    )
    decision = gate(
        ToolRequest(tool="toee_qbo_read", action="get_invoice"), _ctx(None)
    )
    assert decision.allow is False
    assert decision.error_class == "policy_blocked"


def test_allows_non_qbo_tools_regardless_of_email_link() -> None:
    # The email-link gate governs accounting reads only; a Shopify read (or any
    # other allowlisted tool) is not subject to it.
    gate = create_external_profile_gate(email_links={})
    decision = gate(
        ToolRequest(tool="toee_shopify_read", action="get_order"), _ctx(VERIFIED)
    )
    assert decision.allow is True


def test_allows_non_qbo_tool_for_unmatched_identity() -> None:
    gate = create_external_profile_gate(email_links={})
    decision = gate(
        ToolRequest(tool="toee_knowledge_search", action="search"),
        _ctx({"outcome": "unmatched_caller"}),
    )
    assert decision.allow is True
