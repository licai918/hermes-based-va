"""S12: datastore-level Customer Memory correctness rules (PRD workspace/0.0.1/PRD.md
§6.2 R1-R6), against real Postgres (throwaway schema, anti-mock §6.0.1).

R1 (binding selection), R4 (write discipline), R5 (merge three-state), and R6
(fail-closed) already have datastore-level coverage elsewhere: see
``test_datastore_driver_memory.py`` (R1/R4/R6) and ``test_datastore_merge_
provisional.py`` (R5). R2 (content round-trip) is covered at the turn-injection
level by ``test_openrouter_memory_injection.py`` / ``test_copilot_memory_
injection.py``, both against real Postgres.

The one explicit gap this file fills: R3 cross-customer isolation with an
explicit DATASTORE-level test -- two real binding keys in one throwaway schema,
proven in both directions (B never sees A's slots; A still sees its own), with
every persistence assertion reading ``customer_memory_slot`` back via
``conn.cursor()`` directly (never trusting a tool/store return value alone, per
§6.0.1). Both READ entrypoints the rest of the system relies on are covered
independently, since a filter bug could live in either query alone: the governed
``toee_customer_memory.get_preferences`` tool action (PostgresDriver, the write/
read tool path) and ``PostgresGatewayStore.load_customer_memory`` (the S07/S08
turn-time injection read path).
"""

from __future__ import annotations

from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

EXTERNAL = "customer_service_external"
INTERNAL = "internal_copilot"

# Customer A: verified (binds to the Shopify customer id).
_CUSTOMER_A = {
    "outcome": "verified_customer",
    "shopify_customer_id": "gid://shopify/Customer/30001",
}
# Customer B: provisional (unmatched caller, binds to the canonical channel key).
_CUSTOMER_B_PHONE = "+14165550301"
_CUSTOMER_B = {"channel": "sms", "channel_identity": _CUSTOMER_B_PHONE}


def _upsert(driver, *, identity, key, value):
    result = execute_tool(
        tool="toee_customer_memory",
        action="upsert_preference",
        params={"key": key, "value": value},
        context=ToolExecutionContext(profile=EXTERNAL, identity=identity),
        driver=driver,
    )
    assert result.ok, result
    return result.data["binding_key"]


def _get_preferences(driver, *, identity):
    result = execute_tool(
        tool="toee_customer_memory",
        action="get_preferences",
        params={},
        context=ToolExecutionContext(profile=EXTERNAL, identity=identity),
        driver=driver,
    )
    assert result.ok, result
    return result.data


def _rows_for(conn, binding_key) -> dict[str, str]:
    """Anti-mock assertion (§6.0.1): read straight from Postgres, not a tool return."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT slot_name, slot_value FROM customer_memory_slot WHERE binding_key = %s",
            (binding_key,),
        )
        return {name: value for name, value in cur.fetchall()}


def test_get_preferences_never_leaks_across_binding_keys_either_direction(datastore) -> None:
    """R3: two real customers (one verified, one provisional), the SAME slot name
    but DIFFERENT values -- the sharpest isolation probe. A dropped/broadened
    ``WHERE binding_key = ...`` filter (or a read that unions rows) would surface
    as the WRONG value for a customer, not merely an extra key, so this fails hard
    if isolation ever regresses (not a tautology: flip the assertion below at
    verification time and it goes red).
    """
    driver, conn, _ = datastore
    key_a = _upsert(driver, identity=_CUSTOMER_A, key="channel_preference", value="sms")
    key_b = _upsert(driver, identity=_CUSTOMER_B, key="channel_preference", value="email")
    assert key_a != key_b
    assert key_a == "gid://shopify/Customer/30001"
    assert key_b == f"provisional:sms:{_CUSTOMER_B_PHONE}"

    # (1) The governed READ tool action (execute_tool -> PostgresDriver -> real SQL).
    prefs_a = _get_preferences(driver, identity=_CUSTOMER_A)
    prefs_b = _get_preferences(driver, identity=_CUSTOMER_B)
    assert prefs_a["preferences"] == {"channel_preference": "sms"}  # A still sees own
    assert prefs_b["preferences"] == {"channel_preference": "email"}  # B sees own, never A's
    assert prefs_a["binding_key"] == key_a
    assert prefs_b["binding_key"] == key_b

    # (2) Anti-mock: read the actual rows back directly, independent of (1).
    assert _rows_for(conn, key_a) == {"channel_preference": "sms"}
    assert _rows_for(conn, key_b) == {"channel_preference": "email"}

    # (3) Belt-and-suspenders: a single raw scan across BOTH keys shows exactly the
    # two expected (binding_key, value) pairs -- not e.g. 4 rows from a cross-write,
    # or either value attached to the wrong key.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT binding_key, slot_value FROM customer_memory_slot "
            "WHERE binding_key IN (%s, %s) ORDER BY binding_key",
            (key_a, key_b),
        )
        all_rows = cur.fetchall()
    assert all_rows == sorted([(key_a, "sms"), (key_b, "email")])


def test_load_customer_memory_never_leaks_across_binding_keys(datastore) -> None:
    """Same isolation probe against the OTHER read entrypoint the turn-time
    injection uses (PostgresGatewayStore.load_customer_memory, S07/S08) -- a
    filter bug could live in this query independently of get_preferences'."""
    driver, conn, _ = datastore
    key_a = _upsert(
        driver, identity=_CUSTOMER_A, key="contact_time_preference", value="mornings"
    )
    key_b = _upsert(
        driver, identity=_CUSTOMER_B, key="contact_time_preference", value="evenings"
    )

    store = PostgresGatewayStore(connection=conn)
    slots_a = store.load_customer_memory(key_a)
    slots_b = store.load_customer_memory(key_b)

    assert slots_a == [{"slot": "contact_time_preference", "value": "mornings"}]
    assert slots_b == [{"slot": "contact_time_preference", "value": "evenings"}]

    # Anti-mock direct read, independent of the store method under test.
    assert _rows_for(conn, key_a) == {"contact_time_preference": "mornings"}
    assert _rows_for(conn, key_b) == {"contact_time_preference": "evenings"}


def test_clear_preference_for_one_customer_does_not_touch_the_others_row(datastore) -> None:
    """R3 on the delete path: clearing A's slot must not delete B's row for the
    same slot name -- a binding_key-less (or wildcard) DELETE would wipe both."""
    driver, conn, _ = datastore
    key_a = _upsert(
        driver, identity=_CUSTOMER_A, key="delivery_habit_note", value="leave at dock"
    )
    key_b = _upsert(
        driver, identity=_CUSTOMER_B, key="delivery_habit_note", value="ring bell"
    )

    # 0.0.3 S20 (FR-20): clear is an attributed employee/supervisor action, so
    # this isolation probe runs as an internal rep rather than the EXTERNAL
    # customer profile. (0.0.3 S21 extends the EXTERNAL gate to also allow a
    # VERIFIED customer to clear their OWN binding -- see
    # test_datastore_driver_memory.py -- but that's a different authorization
    # path from the rep/supervisor one this isolation probe exercises here.)
    result = execute_tool(
        tool="toee_customer_memory",
        action="clear_preference",
        params={"key": "delivery_habit_note"},
        context=ToolExecutionContext(
            profile=INTERNAL, identity=_CUSTOMER_A, user_id="acct_rep_isolation"
        ),
        driver=driver,
    )
    assert result.ok and result.data["cleared"] is True

    assert _rows_for(conn, key_a) == {}  # A's row gone
    assert _rows_for(conn, key_b) == {"delivery_habit_note": "ring bell"}  # B untouched
