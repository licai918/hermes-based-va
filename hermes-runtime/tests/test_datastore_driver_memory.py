"""Slice 33 / #36: Postgres-backed ``toee_customer_memory`` through ``execute_tool``.

Customer Memory binds to the verified Shopify customer id (Session Identity
Snapshot, ADR-0043) or a canonical provisional channel key derived from context,
fail-closed when no channel identity resolves (ADR-0112, PRD FR-5/S02), over the
fixed four preference slots (ADR-0111). Skip-if-no-DB via the shared ``datastore``
fixture.
"""

from __future__ import annotations

from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

VERIFIED = {
    "outcome": "verified_customer",
    "shopify_customer_id": "gid://shopify/Customer/1001",
}


def _run(driver, action, params, *, identity=None):
    return execute_tool(
        tool="toee_customer_memory",
        action=action,
        params=params,
        context=ToolExecutionContext(profile="customer_service_external", identity=identity),
        driver=driver,
    )


_PROVISIONAL_A = {"channel": "sms", "channel_identity": "+14165550000"}


def test_upsert_then_get_round_trips_on_provisional_binding(datastore) -> None:
    # S02: binding derives from context (S01 ingress identity), never a
    # model-supplied ``channel_identity_id`` param, on the external profile.
    driver, _, _ = datastore
    up = _run(
        driver,
        "upsert_preference",
        {"key": "channel_preference", "value": "sms", "source": "customer_explicit"},
        identity=_PROVISIONAL_A,
    )
    assert up.ok
    assert up.data["stored"] is True
    assert up.data["binding_key"] == "provisional:sms:+14165550000"
    assert up.data["slot"] == "channel_preference"

    got = _run(driver, "get_preferences", {}, identity=_PROVISIONAL_A)
    assert got.ok
    assert got.data["preferences"]["channel_preference"] == "sms"


def test_no_channel_identity_is_policy_blocked_not_shared_provisional(datastore) -> None:
    # R6 fail-closed, against the real Postgres path: no usable channel identity
    # in context => policy_blocked, never the old bare shared "provisional" key.
    driver, _, _ = datastore
    result = _run(
        driver,
        "upsert_preference",
        {"key": "channel_preference", "value": "sms", "channel_identity_id": "+19998887777"},
    )
    assert not result.ok
    assert result.error_class == "policy_blocked"


def test_verified_identity_binds_to_shopify_customer_id(datastore) -> None:
    driver, _, _ = datastore
    up = _run(
        driver,
        "upsert_preference",
        {"key": "contact_time_preference", "value": "mornings"},
        identity=VERIFIED,
    )
    assert up.ok
    assert up.data["binding_key"] == "gid://shopify/Customer/1001"

    got = _run(driver, "get_preferences", {}, identity=VERIFIED)
    assert got.data["binding_key"] == "gid://shopify/Customer/1001"
    assert got.data["preferences"]["contact_time_preference"] == "mornings"


def test_upsert_is_idempotent_overwrite(datastore) -> None:
    driver, _, _ = datastore
    identity = {"channel": "sms", "channel_identity": "+14165550001"}
    _run(driver, "upsert_preference",
         {"key": "channel_preference", "value": "sms"}, identity=identity)
    _run(driver, "upsert_preference",
         {"key": "channel_preference", "value": "email"}, identity=identity)
    got = _run(driver, "get_preferences", {}, identity=identity)
    assert got.data["preferences"]["channel_preference"] == "email"


def test_clear_preference_removes_the_slot(datastore) -> None:
    driver, _, _ = datastore
    identity = {"channel": "sms", "channel_identity": "+14165550002"}
    _run(driver, "upsert_preference",
         {"key": "delivery_habit_note", "value": "leave at dock"}, identity=identity)
    cleared = _run(driver, "clear_preference",
                   {"key": "delivery_habit_note"}, identity=identity)
    assert cleared.ok
    assert cleared.data["cleared"] is True
    got = _run(driver, "get_preferences", {}, identity=identity)
    assert "delivery_habit_note" not in got.data["preferences"]


def test_open_ended_key_is_governed_rejection(datastore) -> None:
    # ADR-0111: only the four v1 slots may be written; an open-ended key is a
    # governed failure, not a silent store.
    driver, _, _ = datastore
    result = _run(driver, "upsert_preference",
                  {"key": "favorite_color", "value": "blue", "channel_identity_id": "c3"})
    assert not result.ok
    assert result.error_class == "unexpected_error"


def test_non_string_value_is_governed_rejection(datastore) -> None:
    driver, _, _ = datastore
    result = _run(driver, "upsert_preference",
                  {"key": "channel_preference", "value": 123, "channel_identity_id": "c4"})
    assert not result.ok
    assert result.error_class == "unexpected_error"
