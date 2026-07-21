"""Ingress Phone Match tests (ADR-0043, ADR-0104).

The Channel Gateway runs match_phone synchronously through governed dispatch
before the agent turn and writes a Session Identity Snapshot (verified /
unmatched / ambiguous). A transient identity-lookup failure is an ingress error
(retryable, ADR-0104), never a fabricated snapshot (ADR-0020).
"""

from __future__ import annotations

from typing import Any

from toee_hermes.drivers.mock import MockDriver, create_identity_mock_handlers
from toee_hermes.errors import ToolDriverError
from toee_hermes.execute import ToolRequest
from toee_hermes.gateway.ingress import (
    SessionIdentitySnapshot,
    match_ingress_email,
    match_ingress_phone,
)
from toee_hermes.tool_gate import ToolExecutionContext

RESOLVED_AT = "2026-06-19T12:00:00.000Z"


def _identity_driver() -> MockDriver:
    return MockDriver(create_identity_mock_handlers())


def test_verified_phone_produces_verified_snapshot() -> None:
    result = match_ingress_phone(
        phone="+14165550101", driver=_identity_driver(), resolved_at=RESOLVED_AT
    )
    assert result.retryable_error is False
    assert result.snapshot == SessionIdentitySnapshot(
        outcome="verified_customer",
        resolved_at=RESOLVED_AT,
        shopify_customer_id="gid://shopify/Customer/1001",
        display_name="Acme Fleet",
    )


def test_unmatched_phone_produces_unmatched_snapshot() -> None:
    result = match_ingress_phone(
        phone="+15195550000", driver=_identity_driver(), resolved_at=RESOLVED_AT
    )
    assert result.snapshot == SessionIdentitySnapshot(
        outcome="unmatched_caller", resolved_at=RESOLVED_AT
    )


def test_ambiguous_phone_produces_ambiguous_snapshot() -> None:
    result = match_ingress_phone(
        phone="+14165550222", driver=_identity_driver(), resolved_at=RESOLVED_AT
    )
    assert result.snapshot == SessionIdentitySnapshot(
        outcome="ambiguous_phone_match",
        resolved_at=RESOLVED_AT,
        shopify_customer_ids=[
            "gid://shopify/Customer/2001",
            "gid://shopify/Customer/2002",
        ],
    )


def test_verified_email_sender_produces_verified_snapshot() -> None:
    # ADR-0052: a single From match is a silent Verified Customer.
    result = match_ingress_email(
        from_address="accounts@acme-fleet.example",
        driver=_identity_driver(),
        resolved_at=RESOLVED_AT,
    )
    assert result.retryable_error is False
    assert result.snapshot == SessionIdentitySnapshot(
        outcome="verified_customer",
        resolved_at=RESOLVED_AT,
        shopify_customer_id="gid://shopify/Customer/1001",
        display_name="Acme Fleet",
    )


def test_unmatched_email_sender_produces_unmatched_snapshot() -> None:
    result = match_ingress_email(
        from_address="stranger@example.com",
        driver=_identity_driver(),
        resolved_at=RESOLVED_AT,
    )
    assert result.snapshot == SessionIdentitySnapshot(
        outcome="unmatched_caller", resolved_at=RESOLVED_AT
    )


class _FailingDriver:
    kind = "mock"

    def execute(self, request: ToolRequest, context: ToolExecutionContext) -> Any:
        raise ToolDriverError("vendor_timeout", "match_phone upstream 503")


def test_transient_identity_failure_is_retryable() -> None:
    result = match_ingress_phone(
        phone="+14165550101", driver=_FailingDriver(), resolved_at=RESOLVED_AT
    )
    assert result.snapshot is None
    assert result.retryable_error is True
    assert result.error_class == "vendor_timeout"


def test_transient_email_identity_failure_is_retryable() -> None:
    result = match_ingress_email(
        from_address="accounts@acme-fleet.example",
        driver=_FailingDriver(),
        resolved_at=RESOLVED_AT,
    )
    assert result.snapshot is None
    assert result.retryable_error is True
    assert result.error_class == "vendor_timeout"
