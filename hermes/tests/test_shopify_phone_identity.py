"""Shopify phone identity helper tests."""

from __future__ import annotations

from toee_hermes.identity.shopify_phone import (
    customer_display_name,
    filter_customers_by_phone,
    shopify_customer_gid,
)


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
