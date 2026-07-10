"""Shopify customer phone matching helpers for Ingress Phone Match (ADR-0043/0128)."""

from __future__ import annotations

from typing import Any

from toee_hermes.gateway.normalize import normalize_e164


def shopify_customer_gid(raw_id: object) -> str | None:
    """Normalize a Shopify customer id to the mock contract gid form."""
    if raw_id is None:
        return None
    text = str(raw_id)
    if text.startswith("gid://shopify/Customer/"):
        return text
    if text.isdigit():
        return f"gid://shopify/Customer/{text}"
    return None


def customer_display_name(customer: dict[str, Any]) -> str:
    """Human-readable label for Workbench identity summary."""
    company = customer.get("company")
    if isinstance(company, str) and company.strip():
        return company.strip()
    default_address = customer.get("default_address")
    if isinstance(default_address, dict):
        addr_company = default_address.get("company")
        if isinstance(addr_company, str) and addr_company.strip():
            return addr_company.strip()
    first = customer.get("first_name") or ""
    last = customer.get("last_name") or ""
    name = f"{first} {last}".strip()
    if name:
        return name
    gid = shopify_customer_gid(customer.get("id"))
    if gid:
        return gid.rsplit("/", 1)[-1]
    return "Shopify customer"


def _normalize_phone(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return normalize_e164(value)
    except Exception:  # noqa: BLE001 - reject unparseable vendor phone values
        digits = "".join(ch for ch in value if ch.isdigit())
        return digits or None


def filter_customers_by_phone(
    customers: list[dict[str, Any]], phone: str
) -> list[dict[str, Any]]:
    """Keep Shopify customer records whose registered phone matches ``phone``."""
    target = _normalize_phone(phone)
    if target is None:
        return []
    matches: list[dict[str, Any]] = []
    for customer in customers:
        registered = _normalize_phone(customer.get("phone"))
        if registered is None:
            continue
        if registered == target:
            matches.append(customer)
    return matches
