"""Datastore handlers for ``toee_identity_lookup`` (ADR-0043/0060).

Read-only resolution against the Identity Graph (``identity_link``): a channel
identity (phone / email) maps to zero, one, or many Shopify customers, yielding
an Unmatched Caller, a verified customer, or an ambiguous match. Customer Email
Link readiness (for accounting reads) is the presence of an email link row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._common import read_string

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
        return _with_resolved_at({"outcome": "unmatched_caller"}, params)
    if len(ids) == 1:
        return _with_resolved_at(
            {"outcome": "verified_customer", "shopify_customer_id": ids[0]}, params
        )
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
