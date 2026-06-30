"""Workbench identity summary formatting (ADR-0082)."""

from __future__ import annotations

from toee_hermes.gateway.normalize import normalize_e164
from toee_hermes.identity.shopify_phone import shopify_customer_gid


def is_shopify_customer_gid(value: str) -> bool:
    return shopify_customer_gid(value) is not None


def format_phone_display(phone: str) -> str:
    """Human-friendly phone label for queue identity column."""
    trimmed = phone.strip()
    if not trimmed:
        return ""
    try:
        e164 = normalize_e164(trimmed)
    except Exception:  # noqa: BLE001 - show raw channel identity when unparseable
        return trimmed
    if e164.startswith("+1") and len(e164) == 12:
        digits = e164[2:]
        return f"+1 ({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return e164


def display_name_from_match_result(match_result: object) -> str | None:
    if not isinstance(match_result, dict):
        return None
    for key in ("company_name", "display_name"):
        value = match_result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def format_identity_summary(
    *,
    channel_identity: str,
    shopify_customer_id: str | None = None,
    display_name: str | None = None,
) -> str:
    """ADR-0082 queue identity: verified name + phone, else bare phone."""
    phone = format_phone_display(channel_identity)
    gid = (shopify_customer_id or "").strip()
    label = (display_name or "").strip()
    if not label and gid and not is_shopify_customer_gid(gid):
        # ponytail: dev seed / pre-0128 rows stored a human label in shopify_customer_id.
        label = gid
        gid = ""

    if label or gid:
        if label and phone:
            return f"Verified: {label} · {phone}"
        if label:
            return f"Verified: {label}"
        if phone:
            return f"Verified: {phone}"
        return f"Verified: {gid.rsplit('/', 1)[-1]}"
    return phone
