"""Datastore handlers for ``toee_identity_lookup`` (ADR-0043/0060).

Resolves channel identity (phone / email) against the Identity Graph
(``identity_link``), with an optional Composio-backed Shopify fallback when no
local link exists (ADR-0128). Customer Email Link readiness is the presence of
an email link row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._common import new_id, read_string
from ..shopify_identity import ShopifyPhoneMatch, lookup_shopify_customers_by_phone
from toee_hermes.identity.summary import display_name_from_match_result

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext

# Text-first identity is phone-based over SMS (ADR-0013 shared SMS/voice identity).
_PHONE_CHANNEL = "sms"
_EMAIL_CHANNEL = "email"


def _with_resolved_at(result: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    resolved_at = read_string(params, "resolved_at", "resolvedAt")
    if resolved_at is not None:
        return {**result, "resolved_at": resolved_at}
    return result


def _upsert_identity_link(
    conn, *, channel: str, channel_identity: str, shopify_customer_id: str
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO identity_link
                (id, channel, channel_identity, shopify_customer_id, match_status)
            VALUES (%s, %s, %s, %s, 'verified')
            ON CONFLICT (channel, channel_identity, shopify_customer_id) DO UPDATE SET
                match_status = EXCLUDED.match_status,
                updated_at = now()
            """,
            (
                new_id("idl"),
                channel,
                channel_identity,
                shopify_customer_id,
            ),
        )


def _verified_result(
    match: ShopifyPhoneMatch, params: dict[str, Any]
) -> dict[str, Any]:
    return _with_resolved_at(
        {
            "outcome": "verified_customer",
            "shopify_customer_id": match.shopify_customer_id,
            "company_name": match.display_name,
        },
        params,
    )


def _shopify_phone_fallback(
    conn, channel: str, channel_identity: str, params: dict[str, Any]
) -> dict[str, Any] | None:
    if channel != _PHONE_CHANNEL:
        return None
    matches = lookup_shopify_customers_by_phone(channel_identity)
    if matches is None:
        return None
    if not matches:
        return _with_resolved_at({"outcome": "unmatched_caller"}, params)
    if len(matches) == 1:
        _upsert_identity_link(
            conn,
            channel=channel,
            channel_identity=channel_identity,
            shopify_customer_id=matches[0].shopify_customer_id,
        )
        return _verified_result(matches[0], params)
    return _with_resolved_at(
        {
            "outcome": "ambiguous_phone_match",
            "shopify_customer_ids": [match.shopify_customer_id for match in matches],
        },
        params,
    )


def _display_name_from_snapshots(
    conn, channel: str, channel_identity: str
) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT match_result FROM session_identity_snapshot
            WHERE channel = %s AND channel_identity = %s
              AND match_result->>'outcome' = 'verified_customer'
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            (channel, channel_identity),
        )
        row = cur.fetchone()
    return display_name_from_match_result(row[0]) if row else None


def _enrich_company_name_from_shopify(
    channel: str,
    channel_identity: str,
    shopify_customer_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    if result.get("company_name") or channel != _PHONE_CHANNEL:
        return result
    matches = lookup_shopify_customers_by_phone(channel_identity)
    if not matches:
        return result
    for match in matches:
        if match.shopify_customer_id == shopify_customer_id:
            result["company_name"] = match.display_name
            break
    return result


def _verified_from_link(
    conn,
    channel: str,
    channel_identity: str,
    shopify_customer_id: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "outcome": "verified_customer",
        "shopify_customer_id": shopify_customer_id,
    }
    company = _display_name_from_snapshots(conn, channel, channel_identity)
    if company:
        result["company_name"] = company
    result = _enrich_company_name_from_shopify(
        channel, channel_identity, shopify_customer_id, result
    )
    return _with_resolved_at(result, params)


def _match(conn, channel: str, channel_identity: str | None, params: dict[str, Any]) -> Any:
    if channel_identity is None:
        return _with_resolved_at({"outcome": "unmatched_caller"}, params)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT shopify_customer_id FROM identity_link
            WHERE channel = %s AND channel_identity = %s
              AND shopify_customer_id IS NOT NULL
            ORDER BY shopify_customer_id
            """,
            (channel, channel_identity),
        )
        ids = [row[0] for row in cur.fetchall()]
    if not ids:
        fallback = _shopify_phone_fallback(conn, channel, channel_identity, params)
        if fallback is not None:
            return fallback
        return _with_resolved_at({"outcome": "unmatched_caller"}, params)
    if len(ids) == 1:
        return _verified_from_link(conn, channel, channel_identity, ids[0], params)
    # More than one candidate customer: never auto-merge in v1 (ADR-0044). The
    # "phone" outcome name is the established contract the mock also uses for email.
    return _with_resolved_at(
        {"outcome": "ambiguous_phone_match", "shopify_customer_ids": ids}, params
    )


def _match_phone(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    phone = read_string(params, "phone", "from_phone", "fromPhone")
    channel = read_string(params, "channel") or _PHONE_CHANNEL
    return _match(conn, channel, phone, params)


def _match_email_sender(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    from_address = read_string(params, "from_address", "fromAddress")
    return _match(conn, _EMAIL_CHANNEL, from_address, params)


def _get_email_link_status(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    shopify_customer_id = read_string(params, "shopify_customer_id", "shopifyCustomerId")
    email = read_string(params, "email")
    with conn.cursor() as cur:
        if shopify_customer_id is not None:
            cur.execute(
                "SELECT 1 FROM identity_link WHERE channel = %s AND shopify_customer_id = %s LIMIT 1",
                (_EMAIL_CHANNEL, shopify_customer_id),
            )
        elif email is not None:
            cur.execute(
                "SELECT 1 FROM identity_link WHERE channel = %s AND channel_identity = %s LIMIT 1",
                (_EMAIL_CHANNEL, email),
            )
        else:
            return {"status": "unlinked"}
        linked = cur.fetchone() is not None
    return {"status": "linked" if linked else "unlinked"}


def identity_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the identity-lookup datastore tool."""
    return {
        "toee_identity_lookup": {
            "match_phone": _match_phone,
            "match_email_sender": _match_email_sender,
            "get_email_link_status": _get_email_link_status,
        }
    }
