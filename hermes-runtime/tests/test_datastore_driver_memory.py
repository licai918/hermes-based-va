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


def _run(
    driver,
    action,
    params,
    *,
    identity=None,
    profile="customer_service_external",
    user_id=None,
):
    return execute_tool(
        tool="toee_customer_memory",
        action=action,
        params=params,
        context=ToolExecutionContext(profile=profile, identity=identity, user_id=user_id),
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


def test_evidence_at_max_length_is_accepted(datastore) -> None:
    driver, _, _ = datastore
    result = _run(driver, "upsert_preference",
                  {"key": "delivery_habit_note", "value": "x", "evidence": "x" * 500},
                  identity=_PROVISIONAL_A)
    assert result.ok


def test_evidence_over_max_length_is_governed_rejection(datastore) -> None:
    driver, _, _ = datastore
    result = _run(driver, "upsert_preference",
                  {"key": "delivery_habit_note", "value": "x", "evidence": "x" * 501},
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


def test_internal_copilot_with_user_id_persists_employee_confirmed_source(
    datastore,
) -> None:
    # §6.1 matrix / R1: a write dispatched WITH an actor (context.user_id, PRD §9)
    # persists source=employee_confirmed -- read back directly from Postgres, not
    # just the tool's own return value.
    driver, conn, _ = datastore
    up = _run(
        driver, "upsert_preference",
        {"key": "contact_time_preference", "value": "mornings only"},
        identity=VERIFIED, profile="internal_copilot", user_id="acct_rep_s01",
    )
    assert up.ok
    assert up.data["source"] == "employee_confirmed"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT source FROM customer_memory_slot "
            "WHERE binding_key = %s AND slot_name = %s",
            (up.data["binding_key"], "contact_time_preference"),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "employee_confirmed"


def test_internal_copilot_without_user_id_persists_copilot_agent_source(
    datastore,
) -> None:
    # §6.1 matrix / R1: a draft-turn-shaped write (no context.user_id -- the
    # unbound S20 path) persists source=copilot_agent, never employee_confirmed
    # -- read back directly from Postgres.
    driver, conn, _ = datastore
    up = _run(
        driver, "upsert_preference",
        {"key": "contact_time_preference", "value": "mornings only"},
        identity=VERIFIED, profile="internal_copilot",
    )
    assert up.ok
    assert up.data["source"] == "copilot_agent"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT source FROM customer_memory_slot "
            "WHERE binding_key = %s AND slot_name = %s",
            (up.data["binding_key"], "contact_time_preference"),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "copilot_agent"


def test_internal_copilot_channel_identity_id_param_is_ignored(datastore) -> None:
    # R3/FR-5: the carve-out is removed -- a model-supplied channel_identity_id no
    # longer binds on internal_copilot either, against the real Postgres path. No
    # context identity => policy_blocked, never a bound provisional:{param} key.
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
    assert not result.ok
    assert result.error_class == "policy_blocked"


def test_removal_tripwire_internal_copilot_channel_identity_id_never_binds(
    datastore,
) -> None:
    """R3 / PRD §6.0.4 removal tripwire -- replaces the deleted S15
    characterization test this used to be (``test_dispatch_route_correction_
    persists_but_misses_a_verified_customers_read_key``), which documented the
    ``internal_copilot`` ``channel_identity_id`` param carve-out (``resolve_
    customer_memory_binding`` used to unconditionally mint
    ``provisional:{channel_identity_id}``). That carve-out no longer exists.

    Reproduces the exact scenario the dispatch route hits when its case-identity
    lookup finds nothing (``tool_dispatch_app._resolve_case_identity`` -> ``None``:
    memory disabled, unknown case, or a store error) and only the model-supplied
    ``channel_identity_id`` param remains -- profile ``internal_copilot``,
    ``identity=None``, ``channel_identity_id`` = a case's Shopify customer id (the
    same value the deleted S15 test used). The write must be ``policy_blocked``
    and NO row may land in Postgres under the old carve-out's dead
    ``provisional:{channel_identity_id}`` key. If the carve-out ever silently
    returns, this test goes red: the write would succeed and that row would exist.
    """
    driver, conn, _ = datastore
    shopify_customer_id = "gid://shopify/Customer/1001"
    dead_key = f"provisional:{shopify_customer_id}"

    result = _run(
        driver, "upsert_preference",
        {
            "key": "contact_time_preference",
            "value": "mornings only",
            "channel_identity_id": shopify_customer_id,
        },
        profile="internal_copilot",
    )

    assert not result.ok
    assert result.error_class == "policy_blocked"
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM customer_memory_slot WHERE binding_key = %s",
            (dead_key,),
        )
        assert cur.fetchone()[0] == 0


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
