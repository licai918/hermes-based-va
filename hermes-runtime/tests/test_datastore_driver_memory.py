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
    # 0.0.3 S20 (FR-20): clear is a governed employee/supervisor action, same
    # attributed-actor requirement as dismiss_proposal.
    driver, _, _ = datastore
    identity = {"channel": "sms", "channel_identity": "+14165550002"}
    _run(driver, "upsert_preference",
         {"key": "delivery_habit_note", "value": "leave at dock"}, identity=identity)
    cleared = _run(driver, "clear_preference",
                   {"key": "delivery_habit_note"}, identity=identity,
                   profile="internal_copilot", user_id="acct_rep_1")
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


# --- actor attribution (S02, PRD §9 / FR-4 / R2) -----------------------------


def test_internal_copilot_with_user_id_persists_the_actor_account_id(
    datastore,
) -> None:
    # R2/FR-4: a write dispatched WITH an actor (context.user_id, PRD §9) persists
    # that account id in the actor column -- read back directly from Postgres, not
    # just the tool's own return value.
    driver, conn, _ = datastore
    up = _run(
        driver, "upsert_preference",
        {"key": "contact_time_preference", "value": "mornings only"},
        identity=VERIFIED, profile="internal_copilot", user_id="acct_rep_s01",
    )
    assert up.ok

    with conn.cursor() as cur:
        cur.execute(
            "SELECT actor_account_id FROM customer_memory_slot "
            "WHERE binding_key = %s AND slot_name = %s",
            (up.data["binding_key"], "contact_time_preference"),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "acct_rep_s01"


def test_internal_copilot_without_user_id_persists_null_actor(datastore) -> None:
    # R2/FR-4: a draft-turn-shaped write (no context.user_id -- the unbound S20
    # path) persists a NULL actor -- read back directly from Postgres.
    driver, conn, _ = datastore
    up = _run(
        driver, "upsert_preference",
        {"key": "contact_time_preference", "value": "mornings only"},
        identity=VERIFIED, profile="internal_copilot",
    )
    assert up.ok

    with conn.cursor() as cur:
        cur.execute(
            "SELECT actor_account_id FROM customer_memory_slot "
            "WHERE binding_key = %s AND slot_name = %s",
            (up.data["binding_key"], "contact_time_preference"),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] is None


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


# --- dismiss_proposal (0.0.3 S15, FR-16/FR-17) ------------------------------
# Acceptance criterion ①: "dismissed leaves no slot but an audit row -- read
# back directly from Postgres."


def test_dismiss_proposal_persists_no_slot_but_writes_an_audit_row(datastore) -> None:
    driver, conn, _ = datastore
    result = _run(
        driver,
        "dismiss_proposal",
        {"key": "channel_preference", "value": "sms", "evidence": "text me on sms"},
        identity=_PROVISIONAL_A,
        profile="internal_copilot",
        user_id="acct_rep_1",
    )
    assert result.ok
    assert result.data["dismissed"] is True
    binding_key = result.data["binding_key"]

    with conn.cursor() as cur:
        # No slot: a dismissed proposal can't quietly persist (US17).
        cur.execute(
            "SELECT count(*) FROM customer_memory_slot "
            "WHERE binding_key = %s AND slot_name = %s",
            (binding_key, "channel_preference"),
        )
        assert cur.fetchone()[0] == 0

        # But an audit row exists, attributed to the deciding employee.
        cur.execute(
            "SELECT account_id, action, target_type, target_id, details "
            "FROM workbench_audit_log WHERE action = 'proposal_dismissed' "
            "AND target_id = %s",
            ("channel_preference",),
        )
        row = cur.fetchone()
    assert row is not None
    account_id, action, target_type, target_id, details = row
    assert account_id == "acct_rep_1"
    assert action == "proposal_dismissed"
    assert target_type == "customer_memory_slot"
    assert target_id == "channel_preference"
    assert details["slot"] == "channel_preference"
    assert details["value"] == "sms"
    assert details["evidence"] == "text me on sms"


def test_dismiss_proposal_with_no_actor_is_policy_blocked(datastore) -> None:
    driver, conn, _ = datastore
    result = _run(
        driver,
        "dismiss_proposal",
        {"key": "channel_preference", "value": "sms"},
        identity=_PROVISIONAL_A,
        profile="internal_copilot",
    )
    assert not result.ok
    assert result.error_class == "policy_blocked"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM workbench_audit_log WHERE action = 'proposal_dismissed'"
        )
        assert cur.fetchone()[0] == 0


# --- clear_preference audit (0.0.3 S20, FR-20) ------------------------------
# Acceptance criterion ①(b): "a clear removes the slot AND persists an
# attributed preference_cleared audit entry, read back from the real
# workbench_audit_log" -- closes the 0.0.2 PAC-1 caveat (a clear used to leave
# zero trace). Plus: "a handler test proving clear with no actor is
# policy_blocked."


def test_clear_preference_with_no_actor_is_policy_blocked(datastore) -> None:
    driver, conn, _ = datastore
    identity = {"channel": "sms", "channel_identity": "+14165550098"}
    _run(driver, "upsert_preference",
         {"key": "delivery_habit_note", "value": "leave at dock"}, identity=identity)

    result = _run(driver, "clear_preference", {"key": "delivery_habit_note"}, identity=identity)
    assert not result.ok
    assert result.error_class == "policy_blocked"

    # Fail-closed, not fail-open: the slot survives an unattributed clear attempt.
    got = _run(driver, "get_preferences", {}, identity=identity)
    assert got.data["preferences"]["delivery_habit_note"] == "leave at dock"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM workbench_audit_log WHERE action = 'preference_cleared'"
        )
        assert cur.fetchone()[0] == 0


def test_clear_preference_persists_an_attributed_audit_row(datastore) -> None:
    driver, conn, _ = datastore
    identity = {"channel": "sms", "channel_identity": "+14165550097"}
    _run(driver, "upsert_preference",
         {"key": "communication_style_note", "value": "prefers texts"}, identity=identity)

    cleared = _run(
        driver, "clear_preference", {"key": "communication_style_note"},
        identity=identity, profile="internal_copilot", user_id="acct_sup_1",
    )
    assert cleared.ok
    assert cleared.data["cleared"] is True
    binding_key = cleared.data["binding_key"]

    # The slot is really gone -- read back from Postgres, not the response echo.
    got = _run(driver, "get_preferences", {}, identity=identity)
    assert "communication_style_note" not in got.data["preferences"]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT account_id, action, target_type, target_id, details "
            "FROM workbench_audit_log WHERE action = 'preference_cleared' "
            "AND target_id = %s",
            ("communication_style_note",),
        )
        row = cur.fetchone()
    assert row is not None
    account_id, action, target_type, target_id, details = row
    assert account_id == "acct_sup_1"
    assert action == "preference_cleared"
    assert target_type == "customer_memory_slot"
    assert target_id == "communication_style_note"
    assert details["slot"] == "communication_style_note"
    assert details["binding_key"] == binding_key
    assert details["initiator"] == "rep"


# --- clear_preference / get_my_memory_summary: verified customer self-service
# (0.0.3 S21, FR-21, NFR-2) -- EXTENDS the S20 gate above to also authorize a
# VERIFIED customer clearing their OWN binding on the EXTERNAL profile, and
# adds the verified-only customer-safe summary read. The make-or-break
# property: an UNVERIFIED caller gets ZERO data and CANNOT clear.


def test_clear_preference_verified_external_customer_clears_own_slot_and_audits(
    datastore,
) -> None:
    driver, conn, _ = datastore
    identity = VERIFIED
    _run(driver, "upsert_preference",
         {"key": "channel_preference", "value": "sms"}, identity=identity)

    cleared = _run(driver, "clear_preference", {"key": "channel_preference"}, identity=identity)
    assert cleared.ok
    assert cleared.data["cleared"] is True
    binding_key = cleared.data["binding_key"]
    assert binding_key == identity["shopify_customer_id"]

    # The slot is really gone -- read back from Postgres.
    got = _run(driver, "get_preferences", {}, identity=identity)
    assert "channel_preference" not in got.data["preferences"]

    # Audited: customer-initiated, NULL actor (the customer is not a workbench
    # account) -- distinguishable from a rep clear via details.initiator.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT account_id, action, target_type, target_id, details "
            "FROM workbench_audit_log WHERE action = 'preference_cleared' "
            "AND target_id = %s",
            ("channel_preference",),
        )
        row = cur.fetchone()
    assert row is not None
    account_id, action, target_type, target_id, details = row
    assert account_id is None
    assert action == "preference_cleared"
    assert target_type == "customer_memory_slot"
    assert target_id == "channel_preference"
    assert details["binding_key"] == binding_key
    assert details["initiator"] == "customer"


def test_clear_preference_unverified_external_caller_is_policy_blocked(datastore) -> None:
    # FR-21/US13: a provisional (unmatched/ambiguous) EXTERNAL caller must
    # still be policy_blocked -- a resolvable provisional binding is not
    # authorization.
    driver, conn, _ = datastore
    identity = {"channel": "sms", "channel_identity": "+14165550080"}
    _run(driver, "upsert_preference",
         {"key": "delivery_habit_note", "value": "leave at dock"}, identity=identity)

    result = _run(driver, "clear_preference", {"key": "delivery_habit_note"}, identity=identity)
    assert not result.ok
    assert result.error_class == "policy_blocked"

    # Fail-closed, not fail-open: the slot survives.
    got = _run(driver, "get_preferences", {}, identity=identity)
    assert got.data["preferences"]["delivery_habit_note"] == "leave at dock"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM workbench_audit_log WHERE action = 'preference_cleared'"
        )
        assert cur.fetchone()[0] == 0


def test_clear_preference_unmatched_external_caller_is_policy_blocked(datastore) -> None:
    # No channel identity in context at all -- resolve_customer_memory_binding
    # itself fails closed, and the verified-only gate rejects before that too.
    driver, _, _ = datastore
    result = _run(driver, "clear_preference", {"key": "delivery_habit_note"})
    assert not result.ok
    assert result.error_class == "policy_blocked"


def test_get_my_memory_summary_verified_external_returns_slot_values_only(
    datastore,
) -> None:
    driver, _, _ = datastore
    identity = VERIFIED
    _run(driver, "upsert_preference",
         {"key": "channel_preference", "value": "sms"}, identity=identity)
    _run(driver, "upsert_preference",
         {"key": "contact_time_preference", "value": "mornings"}, identity=identity)

    result = _run(driver, "get_my_memory_summary", {}, identity=identity)
    assert result.ok
    assert result.data == {
        "preferences": {
            "channel_preference": "sms",
            "contact_time_preference": "mornings",
        }
    }
    # No internal metadata: no source, actor, timestamps, or binding_key.
    assert set(result.data.keys()) == {"preferences"}


def test_get_my_memory_summary_unverified_provisional_caller_gets_no_data(
    datastore,
) -> None:
    driver, _, _ = datastore
    identity = {"channel": "sms", "channel_identity": "+14165550081"}
    _run(driver, "upsert_preference",
         {"key": "channel_preference", "value": "sms"}, identity=identity)

    result = _run(driver, "get_my_memory_summary", {}, identity=identity)
    assert not result.ok
    assert result.error_class == "policy_blocked"
    assert result.data is None


def test_get_my_memory_summary_unmatched_caller_gets_no_data(datastore) -> None:
    driver, _, _ = datastore
    result = _run(driver, "get_my_memory_summary", {})
    assert not result.ok
    assert result.error_class == "policy_blocked"
    assert result.data is None


def test_get_my_memory_summary_internal_copilot_verified_still_requires_verified_identity(
    datastore,
) -> None:
    # The gate is verified-identity, not profile -- an internal_copilot call
    # with no resolvable/verified identity is blocked the same way.
    driver, _, _ = datastore
    result = _run(driver, "get_my_memory_summary", {}, profile="internal_copilot")
    assert not result.ok
    assert result.error_class == "policy_blocked"


# --- get_memory_audit (0.0.3 S20, FR-20: supervisor memory audit view) ------
# "The audit view's full write history is the UNION of two sources": current
# slot rows (who wrote what's live now) and the workbench_audit_log trail for
# the binding. The S16 boundary requires proposal_dismissed rows to surface
# here already, not be filtered out.


def test_get_memory_audit_surfaces_current_slot_attribution(datastore) -> None:
    driver, _, _ = datastore
    identity = {"channel": "sms", "channel_identity": "+14165550096"}
    _run(
        driver, "upsert_preference", {"key": "channel_preference", "value": "sms"},
        identity=identity, profile="internal_copilot", user_id="acct_rep_2",
    )

    result = _run(driver, "get_memory_audit", {}, identity=identity)
    assert result.ok
    slots = result.data["slots"]
    assert len(slots) == 1
    assert slots[0]["slot_name"] == "channel_preference"
    assert slots[0]["slot_value"] == "sms"
    assert slots[0]["source"] == "employee_confirmed"
    assert slots[0]["actor_account_id"] == "acct_rep_2"
    assert slots[0]["updated_at"] is not None


def test_get_memory_audit_surfaces_dismissed_and_cleared_history_not_filtered(
    datastore,
) -> None:
    driver, _, _ = datastore
    identity = {"channel": "sms", "channel_identity": "+14165550095"}
    _run(
        driver, "dismiss_proposal",
        {"key": "delivery_habit_note", "value": "back door", "evidence": "leave it out back"},
        identity=identity, profile="internal_copilot", user_id="acct_rep_3",
    )
    _run(
        driver, "upsert_preference", {"key": "channel_preference", "value": "sms"},
        identity=identity, profile="internal_copilot", user_id="acct_rep_3",
    )
    _run(
        driver, "clear_preference", {"key": "channel_preference"},
        identity=identity, profile="internal_copilot", user_id="acct_sup_3",
    )

    result = _run(driver, "get_memory_audit", {}, identity=identity)
    assert result.ok
    # The cleared slot is gone from the live view.
    assert result.data["slots"] == []

    # S16 boundary: dismiss + clear are both already surfaced here (S16 only
    # adds presentation, it does not need a second backend read).
    history = result.data["audit"]
    actions = [row["action"] for row in history]
    assert "proposal_dismissed" in actions
    assert "preference_cleared" in actions
    cleared_row = next(r for r in history if r["action"] == "preference_cleared")
    assert cleared_row["account_id"] == "acct_sup_3"
    dismissed_row = next(r for r in history if r["action"] == "proposal_dismissed")
    assert dismissed_row["account_id"] == "acct_rep_3"


def test_get_memory_audit_surfaces_accepted_slot_and_dismissed_proposal_together(
    datastore,
) -> None:
    """S16 (FR-17): the proposal-history section reads BOTH proposal outcomes
    off this one payload, no second backend read -- accepted (an
    employee_confirmed slot, S15's model: the slot row IS the acceptance
    record) and dismissed (a proposal_dismissed audit row, S15) for the same
    binding, each carrying the fields the section needs: slot+value, actor,
    timestamp.
    """
    driver, _, _ = datastore
    identity = {"channel": "sms", "channel_identity": "+14165550093"}
    _run(
        driver, "upsert_preference", {"key": "channel_preference", "value": "sms"},
        identity=identity, profile="internal_copilot", user_id="acct_rep_4",
    )
    _run(
        driver, "dismiss_proposal",
        {"key": "delivery_habit_note", "value": "back door", "evidence": "leave it out back"},
        identity=identity, profile="internal_copilot", user_id="acct_rep_4",
    )

    result = _run(driver, "get_memory_audit", {}, identity=identity)
    assert result.ok

    slots = result.data["slots"]
    assert len(slots) == 1
    assert slots[0]["slot_name"] == "channel_preference"
    assert slots[0]["slot_value"] == "sms"
    assert slots[0]["source"] == "employee_confirmed"
    assert slots[0]["actor_account_id"] == "acct_rep_4"
    assert slots[0]["updated_at"] is not None

    history = result.data["audit"]
    dismissed_row = next(r for r in history if r["action"] == "proposal_dismissed")
    assert dismissed_row["account_id"] == "acct_rep_4"
    assert dismissed_row["details"]["slot"] == "delivery_habit_note"
    assert dismissed_row["details"]["value"] == "back door"
    assert dismissed_row["created_at"] is not None
