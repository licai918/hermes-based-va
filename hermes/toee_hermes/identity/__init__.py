"""Toee-owned identity helpers (ADR-0128 Layer 2)."""

from .shopify_phone import (
    customer_display_name,
    filter_customers_by_phone,
    shopify_customer_gid,
)
from .summary import (
    display_name_from_match_result,
    format_identity_summary,
    format_phone_display,
    is_shopify_customer_gid,
)

__all__ = [
    "customer_display_name",
    "display_name_from_match_result",
    "filter_customers_by_phone",
    "format_identity_summary",
    "format_phone_display",
    "is_shopify_customer_gid",
    "shopify_customer_gid",
]
