"""Shopify customer lookup for ingress identity fallback (ADR-0128).

When ``identity_link`` has no row for an inbound phone, the datastore identity
handler may resolve the caller through Composio-backed Shopify reads and persist a
new link. Returns ``None`` when Composio is not configured (mock / missing env).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from toee_hermes.drivers.base import resolve_integration_driver
from toee_hermes.errors import ToolDriverError
from toee_hermes.identity.shopify_phone import (
    customer_display_name,
    filter_customers_by_phone,
    shopify_customer_gid,
)

logger = logging.getLogger(__name__)

_SEARCH_ACTION = "SHOPIFY_GET_CUSTOMERS_SEARCH"
_LIST_ACTION = "SHOPIFY_GET_ALL_CUSTOMERS"
_PAGE_SIZE = 250
# ponytail: GET_ALL_CUSTOMERS paginated scan runs on the webhook ack path, so it is
# hard-capped at _MAX_SCAN_PAGES (~10k customers). The upgrade path is
# SHOPIFY_GET_CUSTOMERS_SEARCH when the pinned Composio toolkit exposes it.
_MAX_SCAN_PAGES = 40


@dataclass(frozen=True)
class ShopifyPhoneMatch:
    shopify_customer_id: str
    display_name: str


def _unwrap_customers(raw: dict[str, Any]) -> list[dict[str, Any]]:
    inner = raw.get("response_data")
    payload = inner if isinstance(inner, dict) else raw
    customers = payload.get("customers")
    if isinstance(customers, list):
        return [row for row in customers if isinstance(row, dict)]
    return []


def _shape_matches(
    customers: list[dict[str, Any]], phone: str
) -> list[ShopifyPhoneMatch]:
    shaped: list[ShopifyPhoneMatch] = []
    for customer in filter_customers_by_phone(customers, phone):
        gid = shopify_customer_gid(customer.get("id"))
        if gid is None:
            continue
        shaped.append(
            ShopifyPhoneMatch(
                shopify_customer_id=gid,
                display_name=customer_display_name(customer),
            )
        )
    return shaped


def _composio_client():
    import os

    from toee_hermes.drivers.composio.driver import build_composio_driver

    if resolve_integration_driver() != "composio":
        return None
    if not os.environ.get("COMPOSIO_SHOPIFY_CONNECTED_ACCOUNT_ID"):
        return None
    if not os.environ.get("COMPOSIO_API_KEY"):
        return None
    driver = build_composio_driver()
    return driver._client, os.environ.get("COMPOSIO_SHOPIFY_CONNECTED_ACCOUNT_ID"), os.environ.get(
        "COMPOSIO_USER_ID"
    )


def _execute_shopify(action: str, params: dict[str, Any]) -> dict[str, Any]:
    client_bundle = _composio_client()
    if client_bundle is None:
        raise ToolDriverError(
            "configuration_missing",
            "Shopify identity fallback is not configured.",
        )
    client, connected_account_id, user_id = client_bundle
    try:
        return client.execute_action(
            action=action,
            params=params,
            connected_account_id=connected_account_id,
            user_id=user_id,
        )
    except ToolDriverError:
        raise
    except Exception as err:  # noqa: BLE001 - governed vendor failure for ingress
        raise ToolDriverError(
            "composio_api_error",
            f"Shopify action '{action}' failed during identity lookup: {err}",
        ) from err


def _search_queries(phone: str) -> list[str]:
    from toee_hermes.gateway.normalize import normalize_e164

    queries = []
    try:
        e164 = normalize_e164(phone)
        queries.append(f"phone:{e164}")
        digits = e164.lstrip("+")
        if digits.startswith("1") and len(digits) == 11:
            queries.append(f"phone:{digits[1:]}")
            queries.append(f"phone:{digits}")
    except Exception:  # noqa: BLE001 - fall back to raw phone token
        queries.append(f"phone:{phone}")
    seen: set[str] = set()
    ordered: list[str] = []
    for query in queries:
        if query not in seen:
            seen.add(query)
            ordered.append(query)
    return ordered


# A missing Composio action names the action slug alongside an absence marker;
# require both so a generic vendor "not found" (no customer) doesn't get misread
# as "search tool absent" and fall through to the full catalog scan.
_MISSING_TOOL_MARKERS = (
    "not found",
    "does not exist",
    "no such",
    "unknown action",
    "not available",
    "unrecognized",
    "no tool",
    "invalid action",
)


def _is_missing_search_tool(err: ToolDriverError) -> bool:
    message = str(err).lower()
    if _SEARCH_ACTION.lower() not in message:
        return False
    return any(marker in message for marker in _MISSING_TOOL_MARKERS)


def _lookup_via_search(phone: str) -> list[ShopifyPhoneMatch] | None:
    """Try Composio customer search when the toolkit exposes it; ``None`` if absent."""
    tool_available = False
    for query in _search_queries(phone):
        try:
            raw = _execute_shopify(_SEARCH_ACTION, {"query": query, "limit": 10})
        except ToolDriverError as err:
            if _is_missing_search_tool(err):
                return None
            raise
        tool_available = True
        matches = _shape_matches(_unwrap_customers(raw), phone)
        if matches:
            return matches
    if tool_available:
        return []
    return None


def _lookup_via_pagination(phone: str) -> list[ShopifyPhoneMatch]:
    since_id = ""
    for _page in range(_MAX_SCAN_PAGES):
        params: dict[str, Any] = {
            "limit": _PAGE_SIZE,
            "fields": "id,phone,first_name,last_name,company,default_address",
        }
        if since_id:
            params["since_id"] = since_id
        raw = _execute_shopify(_LIST_ACTION, params)
        customers = _unwrap_customers(raw)
        if not customers:
            return []
        matches = _shape_matches(customers, phone)
        if matches:
            return matches
        since_id = str(customers[-1].get("id") or "")
        if not since_id or len(customers) < _PAGE_SIZE:
            return []
    logger.warning(
        "Shopify phone-match scan hit the %d-page cap (~%d customers) without a "
        "match; pin COMPOSIO_TOOLKIT_VERSION_SHOPIFY so %s is available.",
        _MAX_SCAN_PAGES,
        _MAX_SCAN_PAGES * _PAGE_SIZE,
        _SEARCH_ACTION,
    )
    return []


def lookup_shopify_customers_by_phone(phone: str) -> list[ShopifyPhoneMatch] | None:
    """Resolve Shopify customers by registered phone via Composio.

    Returns ``None`` when Composio Shopify is not configured (caller keeps
    unmatched). Returns an empty list on no match. Raises :class:`ToolDriverError`
    on transient vendor failures so ingress can retry (ADR-0104).
    """
    if _composio_client() is None:
        return None
    search_matches = _lookup_via_search(phone)
    if search_matches is not None:
        return search_matches
    return _lookup_via_pagination(phone)
