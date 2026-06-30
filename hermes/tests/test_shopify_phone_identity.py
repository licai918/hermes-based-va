"""Shopify phone identity helper tests."""

from __future__ import annotations

from toee_hermes.identity.shopify_phone import (
    customer_display_name,
    filter_customers_by_phone,
    shopify_customer_gid,
)
from toee_hermes.identity.summary import format_identity_summary, format_phone_display


def test_shopify_customer_gid_normalizes_numeric_id() -> None:
    assert shopify_customer_gid(1001) == "gid://shopify/Customer/1001"


def test_filter_customers_by_phone_matches_e164_and_formatted() -> None:
    customers = [
        {"id": 1, "phone": "(519) 591-7455", "first_name": "Hot", "last_name": "Wheel"},
        {"id": 2, "phone": "+14165550101", "first_name": "Other"},
    ]
    matches = filter_customers_by_phone(customers, "+15195917455")
    assert len(matches) == 1
    assert matches[0]["id"] == 1


def test_customer_display_name_prefers_company() -> None:
    assert (
        customer_display_name(
            {"id": 1, "first_name": "A", "last_name": "B", "company": "Acme Fleet"}
        )
        == "Acme Fleet"
    )


def test_format_phone_display_north_america() -> None:
    assert format_phone_display("+17786803250") == "+1 (778) 680-3250"


def test_format_identity_summary_verified_name_and_phone() -> None:
    assert (
        format_identity_summary(
            channel_identity="+17786803250",
            shopify_customer_id="gid://shopify/Customer/1019382595648",
            display_name="Hello",
        )
        == "Verified: Hello · +1 (778) 680-3250"
    )


def test_format_identity_summary_verified_gid_only_shows_phone() -> None:
    assert (
        format_identity_summary(
            channel_identity="+17786803250",
            shopify_customer_id="gid://shopify/Customer/1019382595648",
        )
        == "Verified: +1 (778) 680-3250"
    )


def test_format_identity_summary_unmatched_shows_phone_only() -> None:
    assert format_identity_summary(channel_identity="+14165550101") == "+1 (416) 555-0101"
