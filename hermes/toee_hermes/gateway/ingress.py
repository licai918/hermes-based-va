"""Ingress Phone Match — synchronous gateway identity step (ADR-0043, ADR-0104).

When the SMS provider delivers an inbound message, the Channel Gateway resolves the sender
phone through ``toee_identity_lookup.match_phone`` *before* the agent turn and
writes a Session Identity Snapshot (verified / unmatched / ambiguous). The
External Customer Service Profile uses only this snapshot for tool authorization.

A transient identity-lookup failure (vendor timeout / 5xx) is an ingress error
that the route layer maps to a retryable ``500`` (ADR-0104); it never yields a
fabricated snapshot (ADR-0020). No-match and ambiguous-match are normal business
states that resolve to a snapshot and a ``200`` ack.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from toee_hermes.errors import ToolErrorClass
from toee_hermes.execute import ToolDriver, execute_tool
from toee_hermes.plugin.profiles import EXTERNAL
from toee_hermes.tool_gate import ToolExecutionContext

_IDENTITY_TOOL = "toee_identity_lookup"
_MATCH_PHONE = "match_phone"
_MATCH_EMAIL = "match_email_sender"


@dataclass(frozen=True)
class SessionIdentitySnapshot:
    """Per-SMS-Session identity outcome (ADR-0043), mirrors @toee/shared.

    ``shopify_customer_id`` is set only for ``verified_customer``;
    ``shopify_customer_ids`` only for ``ambiguous_phone_match``.
    """

    outcome: str  # verified_customer | unmatched_caller | ambiguous_phone_match
    resolved_at: str
    shopify_customer_id: Optional[str] = None
    shopify_customer_ids: Optional[list[str]] = None
    display_name: Optional[str] = None


@dataclass(frozen=True)
class IngressMatchResult:
    """Either a resolved snapshot, or a retryable ingress error (never both)."""

    snapshot: Optional[SessionIdentitySnapshot] = None
    retryable_error: bool = False
    error_class: Optional[ToolErrorClass] = None


def snapshot_as_identity_dict(snapshot: SessionIdentitySnapshot) -> dict[str, Any]:
    """Session Identity Snapshot as the dict tools and ``pre_llm_call`` consume (ADR-0043)."""
    data: dict[str, Any] = {
        "outcome": snapshot.outcome,
        "resolved_at": snapshot.resolved_at,
    }
    if snapshot.shopify_customer_id:
        data["shopify_customer_id"] = snapshot.shopify_customer_id
    if snapshot.shopify_customer_ids:
        data["shopify_customer_ids"] = list(snapshot.shopify_customer_ids)
    if snapshot.display_name:
        data["company_name"] = snapshot.display_name
    return data


def _to_snapshot(data: object, resolved_at: str) -> SessionIdentitySnapshot:
    record = data if isinstance(data, dict) else {}
    outcome = record.get("outcome")
    at = record.get("resolved_at") or resolved_at
    if outcome == "verified_customer":
        company_name = record.get("company_name")
        return SessionIdentitySnapshot(
            outcome="verified_customer",
            resolved_at=at,
            shopify_customer_id=record.get("shopify_customer_id"),
            display_name=company_name if isinstance(company_name, str) else None,
        )
    if outcome == "ambiguous_phone_match":
        return SessionIdentitySnapshot(
            outcome="ambiguous_phone_match",
            resolved_at=at,
            shopify_customer_ids=list(record.get("shopify_customer_ids") or []),
        )
    # Missing/unknown outcome is treated as unmatched: refuse account disclosure
    # rather than fabricate a verified identity (ADR-0020, ADR-0044).
    return SessionIdentitySnapshot(outcome="unmatched_caller", resolved_at=at)


def match_ingress_phone(
    *, phone: str, driver: ToolDriver, resolved_at: str
) -> IngressMatchResult:
    context = ToolExecutionContext(profile=EXTERNAL)
    result = execute_tool(
        tool=_IDENTITY_TOOL,
        action=_MATCH_PHONE,
        context=context,
        driver=driver,
        params={"phone": phone, "resolved_at": resolved_at},
    )
    if not result.ok:
        return IngressMatchResult(retryable_error=True, error_class=result.error_class)
    return IngressMatchResult(snapshot=_to_snapshot(result.data, resolved_at))


def match_ingress_email(
    *, from_address: str, driver: ToolDriver, resolved_at: str
) -> IngressMatchResult:
    """Email Sender Match — the sibling of :func:`match_ingress_phone` (S17/FR-18).

    Resolves the authenticated From address through ``toee_identity_lookup.
    match_email_sender`` under the same EXTERNAL context, returning the same
    ``IngressMatchResult`` shape (verified / unmatched / ambiguous, or a retryable
    ingress error). ADR-0052: a single From match is a silent Verified Customer, no
    verification ceremony. ADR-0054: only the authenticated From address is matched
    — never Reply-To or a body-supplied address (the route passes the envelope From).
    """
    context = ToolExecutionContext(profile=EXTERNAL)
    result = execute_tool(
        tool=_IDENTITY_TOOL,
        action=_MATCH_EMAIL,
        context=context,
        driver=driver,
        params={"from_address": from_address, "resolved_at": resolved_at},
    )
    if not result.ok:
        return IngressMatchResult(retryable_error=True, error_class=result.error_class)
    return IngressMatchResult(snapshot=_to_snapshot(result.data, resolved_at))
