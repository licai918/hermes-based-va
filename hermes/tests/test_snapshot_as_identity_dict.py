"""Session Identity Snapshot dict shape for tools and pre_llm_call."""

from toee_hermes.gateway.ingress import SessionIdentitySnapshot, snapshot_as_identity_dict


def test_snapshot_as_identity_dict_maps_display_name_to_company_name() -> None:
    snap = SessionIdentitySnapshot(
        outcome="verified_customer",
        resolved_at="2026-06-30T12:00:00Z",
        shopify_customer_id="gid://shopify/Customer/1019382595648",
        display_name="Hello",
    )
    assert snapshot_as_identity_dict(snap) == {
        "outcome": "verified_customer",
        "resolved_at": "2026-06-30T12:00:00Z",
        "shopify_customer_id": "gid://shopify/Customer/1019382595648",
        "company_name": "Hello",
    }
