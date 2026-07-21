"""Mock handlers for ``toee_identity_lookup`` (ports mock/identity.ts, ADR-0060).

Resolves Ingress Phone Match / Email Sender Match to results aligned with the
Session Identity Snapshot semantics of ADR-0043, and reports Customer Email Link
readiness for QBO accounting reads. Data is injectable so the Launch Eval fixture
loader can override the baseline seeded from ``eval/mocks/base.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...errors import ToolDriverError
from .driver import MockHandlerRegistry


@dataclass(frozen=True)
class IdentityMockData:
    # Phone (E.164) -> match record. Missing phone -> Unmatched Caller.
    phone_matches: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Email From address -> match record. Missing address -> Unmatched Caller.
    email_matches: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Customer Email Link readiness keyed by Shopify customer id and/or email.
    # Missing key -> "unlinked" (not ready, blocks accounting reads).
    email_links: dict[str, str] = field(default_factory=dict)


# Baseline seeded from eval/mocks/base.yaml: verified_customer_a is linked, the
# unmatched phone/email are intentionally absent, and ambiguous matches carry
# both candidate Shopify customer ids.
identity_baseline_data = IdentityMockData(
    phone_matches={
        "+14165550101": {
            "outcome": "verified_customer",
            "shopify_customer_id": "gid://shopify/Customer/1001",
            "company_name": "Acme Fleet",
        },
        "+14165550222": {
            "outcome": "ambiguous_phone_match",
            "shopify_customer_ids": [
                "gid://shopify/Customer/2001",
                "gid://shopify/Customer/2002",
            ],
        },
    },
    email_matches={
        "accounts@acme-fleet.example": {
            "outcome": "verified_customer",
            "shopify_customer_id": "gid://shopify/Customer/1001",
            "company_name": "Acme Fleet",
        },
        "shared-inbox@acme-fleet.example": {
            "outcome": "ambiguous_phone_match",
            "shopify_customer_ids": [
                "gid://shopify/Customer/2001",
                "gid://shopify/Customer/2002",
            ],
        },
    },
    email_links={
        "gid://shopify/Customer/1001": "linked",
        "accounts@acme-fleet.example": "linked",
    },
)


def _read_string(params: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = params.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _with_resolved_at(result: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    resolved_at = params.get("resolved_at")
    if isinstance(resolved_at, str) and resolved_at:
        return {**result, "resolved_at": resolved_at}
    return result


def _resolve_match(
    record: dict[str, Any] | None, params: dict[str, Any]
) -> dict[str, Any]:
    if record is None:
        return _with_resolved_at({"outcome": "unmatched_caller"}, params)
    return _with_resolved_at(dict(record), params)


def _email_link_status(data: IdentityMockData, params: dict[str, Any]) -> dict[str, str]:
    candidates = (
        _read_string(params, "shopify_customer_id", "shopifyCustomerId"),
        _read_string(params, "email"),
    )
    for key in candidates:
        if key is None:
            continue
        status = data.email_links.get(key)
        if status is not None:
            return {"status": status}
    return {"status": "unlinked"}


def _link_identity(data: IdentityMockData, params: dict[str, Any]) -> dict[str, Any]:
    """Mock counterpart of the datastore ``link_identity`` action (0.0.3 S05).

    Upserts a verified match record into ``phone_matches``/``email_matches`` so a
    *subsequent* ``match_phone``/``match_email_sender`` call on the SAME driver
    instance resolves ``verified_customer`` -- mirrors the datastore handler's
    ``identity_link`` upsert, just against the injected mock table instead of
    Postgres. ``data`` mutates in place (ponytail: the default arg is the
    process-wide ``identity_baseline_data`` singleton, so under TOOL_BACKEND=mock
    a link made through the running gateway/dispatch process is visible to every
    later request in that process -- dev-only, resets on restart, never touches
    real data).
    """
    channel = _read_string(params, "channel") or "sms"
    channel_identity = _read_string(
        params, "channel_identity", "phone", "from_phone", "fromPhone"
    )
    shopify_customer_id = _read_string(params, "shopify_customer_id", "shopifyCustomerId")
    company_name = _read_string(params, "company_name", "companyName")
    if not channel_identity:
        raise ToolDriverError("unexpected_error", "channel_identity is required.")
    if not shopify_customer_id:
        raise ToolDriverError("unexpected_error", "shopify_customer_id is required.")

    record: dict[str, Any] = {
        "outcome": "verified_customer",
        "shopify_customer_id": shopify_customer_id,
    }
    if company_name:
        record["company_name"] = company_name

    table = data.email_matches if channel == "email" else data.phone_matches
    table[channel_identity] = record

    return {
        "outcome": "linked",
        "channel": channel,
        "channel_identity": channel_identity,
        "shopify_customer_id": shopify_customer_id,
    }


def create_identity_mock_handlers(
    data: IdentityMockData = identity_baseline_data,
) -> MockHandlerRegistry:
    """Build the registry fragment bound to a specific data set.

    The Launch Eval fixture loader passes per-scenario data; the default uses the
    base.yaml baseline.
    """
    # Identity lookup *produces* the Session Identity Snapshot from raw channel
    # identifiers, so its handlers read only ``params`` and ignore ``context``.
    return {
        "toee_identity_lookup": {
            "match_phone": lambda params, context: _resolve_match(
                data.phone_matches.get(
                    _read_string(params, "phone", "from_phone", "fromPhone") or ""
                ),
                params,
            ),
            "match_email_sender": lambda params, context: _resolve_match(
                data.email_matches.get(
                    _read_string(params, "from_address", "fromAddress") or ""
                ),
                params,
            ),
            "get_email_link_status": lambda params, context: _email_link_status(
                data, params
            ),
            "link_identity": lambda params, context: _link_identity(data, params),
        }
    }
