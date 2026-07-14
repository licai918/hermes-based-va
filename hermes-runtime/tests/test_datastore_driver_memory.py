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


def _run(driver, action, params, *, identity=None, profile="customer_service_external"):
    return execute_tool(
        tool="toee_customer_memory",
        action=action,
        params=params,
        context=ToolExecutionContext(profile=profile, identity=identity),
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


# --- write discipline: framework source, value cap, evidence (S03, PRD FR-3) -


def test_value_at_max_length_is_accepted(datastore) -> None:
    driver, _, _ = datastore
    result = _run(driver, "upsert_preference",
                  {"key": "delivery_habit_note", "value": "x" * 200},
                  identity=_PROVISIONAL_A)
    assert result.ok


def test_value_over_max_length_is_governed_rejection(datastore) -> None:
    driver, _, _ = datastore
    result = _run(driver, "upsert_preference",
                  {"key": "delivery_habit_note", "value": "x" * 201},
                  identity=_PROVISIONAL_A)
    assert not result.ok
    assert result.error_class == "unexpected_error"


def test_source_param_cannot_be_forged(datastore) -> None:
    # RK-1: source is framework-derived from context.profile, never the
    # model-supplied tool param, even against the real Postgres path.
    driver, _, _ = datastore
    result = _run(
        driver, "upsert_preference",
        {
            "key": "channel_preference",
            "value": "sms",
            "source": "merged_provisional",  # forged: reserved for the S10 merge path
        },
        identity=_PROVISIONAL_A,
    )
    assert result.ok
    assert result.data["source"] == "customer_explicit"


def test_internal_copilot_profile_resolves_employee_confirmed(datastore) -> None:
    driver, _, _ = datastore
    result = _run(
        driver, "upsert_preference",
        {
            "key": "channel_preference",
            "value": "sms",
            "channel_identity_id": "case:ds-employee-confirmed",
        },
        profile="internal_copilot",
    )
    assert result.ok
    assert result.data["source"] == "employee_confirmed"


def test_dispatch_route_correction_persists_but_misses_a_verified_customers_read_key(
    datastore,
) -> None:
    """S15/PAC-4 real-path check: the Workbench ``/v1/tools:dispatch`` route
    (``tool_dispatch_app.py``) never sets ``ToolExecutionContext.identity`` — it
    only has ``tool``/``action``/``params``/``actor_account_id`` off the request body
    (see ``dispatch()``) — so an employee correction can only bind via the
    ``channel_identity_id`` param carve-out. That carve-out (``resolve_customer_
    memory_binding``) unconditionally mints ``provisional:{channel_identity_id}``.

    This reproduces that exact contract for a VERIFIED customer's case (profile
    ``internal_copilot``, ``identity=None``, ``channel_identity_id`` = the case's
    Shopify customer id — the only case-identifying value the dispatch route has).
    The write DOES hit the real Postgres handler (driver routing works). But the
    customer's own next external turn reads the bare ``shopify_customer_id``
    (``openrouter._load_turn_memory`` -> ``binding_key_from_identity`` on a verified
    identity, no prefix — see ``test_verified_identity_binds_to_shopify_customer_id``
    above). The two keys never match, so the correction is NOT visible on the
    customer's next turn even though the row is really in Postgres.
    """
    driver, conn, _ = datastore
    shopify_customer_id = "gid://shopify/Customer/1001"

    correction = _run(
        driver, "upsert_preference",
        {
            "key": "contact_time_preference",
            "value": "mornings only",
            "channel_identity_id": shopify_customer_id,
        },
        profile="internal_copilot",
    )
    assert correction.ok
    assert correction.data["source"] == "employee_confirmed"
    # Persisted -- but under a "provisional:" key, never the bare Shopify id.
    assert correction.data["binding_key"] == f"provisional:{shopify_customer_id}"
    with conn.cursor() as cur:
        cur.execute(
            "SELECT slot_value FROM customer_memory_slot WHERE binding_key = %s AND slot_name = %s",
            (f"provisional:{shopify_customer_id}", "contact_time_preference"),
        )
        assert cur.fetchone() == ("mornings only",)  # the row is genuinely in Postgres

    # The verified customer's own next external turn reads the BARE shopify id.
    read_back = _run(driver, "get_preferences", {}, identity=VERIFIED)
    assert read_back.data["binding_key"] == shopify_customer_id
    assert "contact_time_preference" not in read_back.data["preferences"]


def test_evidence_is_persisted_and_retrievable(datastore) -> None:
    driver, conn, _ = datastore
    up = _run(
        driver, "upsert_preference",
        {
            "key": "contact_time_preference",
            "value": "after 2pm",
            "evidence": "only text me after 2pm please",
        },
        identity=_PROVISIONAL_A,
    )
    assert up.ok
    assert up.data["evidence"] == "only text me after 2pm please"

    # Retrievable: read it straight back out of Postgres, not just the
    # in-process response the handler happened to echo.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT evidence FROM customer_memory_slot "
            "WHERE binding_key = %s AND slot_name = %s",
            (up.data["binding_key"], "contact_time_preference"),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "only text me after 2pm please"


def test_evidence_is_optional_and_defaults_to_null(datastore) -> None:
    driver, conn, _ = datastore
    up = _run(driver, "upsert_preference",
              {"key": "channel_preference", "value": "sms"},
              identity=_PROVISIONAL_A)
    assert up.ok
    assert up.data["evidence"] is None

    with conn.cursor() as cur:
        cur.execute(
            "SELECT evidence FROM customer_memory_slot "
            "WHERE binding_key = %s AND slot_name = %s",
            (up.data["binding_key"], "channel_preference"),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] is None
