"""0.0.5 S11 (FR-13/FR-14, US7, PAC-3): whole-binding erase against live Postgres.

Live-Postgres half of the mock twin's erase tests in ``hermes/tests/test_memory.py``.
The gate (``resolve_erase_authorization``) and the key derivation
(``erase_binding_keys``) are the SAME shared resolvers both handler modules import
(NFR-7), so this file pins what only real Postgres can prove:

* the four slots and the ``4+1`` audit rows, **asserted to have existed first** --
  a deletion test on an empty store passes without deleting anything;
* a NEIGHBOURING binding survives -- without which ``DELETE FROM
  customer_memory_slot`` with no ``WHERE`` passes every other test here;
* D10: every linked channel's provisional binding is cleared too, so the next
  verified turn's cross-channel merge cannot copy the erased slots back;
* a fail-closed refusal deletes NOTHING (a gate that raised after the delete
  would satisfy ``policy_blocked`` on its own);
* FR-14's tripwire OBSERVES THE STORE: it flags a row the erase left behind
  (deletion reported success, data survived) as well as one written afterwards,
  and it stays quiet on the post-erase merge that D10 made a non-event.
"""

from __future__ import annotations

from hermes_runtime.datastore.handlers.memory import deletion_success_metric
from hermes_runtime.injection_ledger import LAYER_L4
from hermes_runtime.postgres_gateway_store import PostgresGatewayStore
from toee_hermes.drivers.mock.memory import (
    ERASE_REAPPEARANCE_WINDOW_DAYS,
    MEMORY_ACTION_ERASED,
    MEMORY_PREFERENCE_SLOTS,
    deletion_success_payload,
)
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import TOOLS_DISPATCH_ROUTE, ToolExecutionContext

_TOOL = "toee_customer_memory"
_CUSTOMER = "gid://shopify/Customer/1001"
_NEIGHBOUR = "gid://shopify/Customer/2002"
_SUPERVISOR = "acct_supervisor_1"


def _ok(result):
    assert result.ok is True, f"{result.error_class}: {result.message}"
    return result.data


def _verified_identity(customer=_CUSTOMER, *, channel=None, channel_identity=None):
    identity = {"outcome": "verified_customer", "shopify_customer_id": customer}
    if channel is not None:
        identity["channel"] = channel
        identity["channel_identity"] = channel_identity
    return identity


def _run(driver, action, params=None, *, identity, user_id=None, profile="internal_copilot"):
    return execute_tool(
        tool=_TOOL,
        action=action,
        params=params or {},
        context=ToolExecutionContext(
            profile=profile,
            identity=identity,
            user_id=user_id,
            dispatch_route=TOOLS_DISPATCH_ROUTE,
        ),
        driver=driver,
    )


def _seed_all_four(driver, identity) -> None:
    for slot in MEMORY_PREFERENCE_SLOTS:
        _ok(
            _run(
                driver,
                "upsert_preference",
                {"key": slot, "value": f"{slot} value", "evidence": f"said: {slot}"},
                identity=identity,
                user_id="acct_rep_1",
            )
        )


def _rows(conn, sql, args=()):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def _slots(conn, binding_key) -> set[str]:
    return {
        name
        for (name,) in _rows(
            conn,
            "SELECT slot_name FROM customer_memory_slot WHERE binding_key = %s",
            (binding_key,),
        )
    }


def _audit(conn, action, binding_key):
    return _rows(
        conn,
        "SELECT account_id, target_type, target_id, details FROM workbench_audit_log "
        "WHERE action = %s AND details ->> 'binding_key' = %s ORDER BY target_id",
        (action, binding_key),
    )


def _link(conn, channel, channel_identity, customer) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO identity_link
                (id, channel, channel_identity, shopify_customer_id, match_status)
            VALUES (%s, %s, %s, %s, 'verified')
            """,
            (f"idl_{channel}_{channel_identity}", channel, channel_identity, customer),
        )
    conn.commit()


def _erase(driver, identity=None, **kwargs):
    return _run(
        driver,
        "erase_customer_memory",
        identity=identity if identity is not None else _verified_identity(),
        **{"user_id": _SUPERVISOR, **kwargs},
    )


# --- FR-13: the erase itself --------------------------------------------------


def test_erase_removes_every_slot_and_writes_four_plus_one_audit_rows(datastore) -> None:
    driver, conn, _schema = datastore
    identity = _verified_identity()
    _seed_all_four(driver, identity)

    # The half that makes this non-vacuous: the rows are THERE first.
    assert _slots(conn, _CUSTOMER) == set(MEMORY_PREFERENCE_SLOTS)

    erased = _ok(_erase(driver, identity))
    assert erased["erased"] is True
    assert erased["cleared"] == 4

    assert _slots(conn, _CUSTOMER) == set()

    per_slot = _audit(conn, "preference_cleared", _CUSTOMER)
    assert len(per_slot) == 4
    assert {row[2] for row in per_slot} == set(MEMORY_PREFERENCE_SLOTS)
    assert {row[0] for row in per_slot} == {_SUPERVISOR}

    summary = _audit(conn, MEMORY_ACTION_ERASED, _CUSTOMER)
    assert len(summary) == 1
    account_id, target_type, target_id, details = summary[0]
    assert account_id == _SUPERVISOR
    assert target_type == "customer_memory_slot"
    assert target_id == _CUSTOMER
    assert sorted(details["cleared_slots"]) == sorted(MEMORY_PREFERENCE_SLOTS)
    assert details["initiator"] == "rep"


def test_erase_leaves_another_customers_binding_intact(datastore) -> None:
    # Without this assertion, `DELETE FROM customer_memory_slot` with no WHERE
    # clause passes every other test in this file.
    driver, conn, _schema = datastore
    _seed_all_four(driver, _verified_identity())
    _seed_all_four(driver, _verified_identity(_NEIGHBOUR))
    assert _slots(conn, _NEIGHBOUR) == set(MEMORY_PREFERENCE_SLOTS)

    _ok(_erase(driver))

    assert _slots(conn, _CUSTOMER) == set()
    assert _slots(conn, _NEIGHBOUR) == set(MEMORY_PREFERENCE_SLOTS)
    # ...and nobody else's audit trail was written either.
    assert _audit(conn, MEMORY_ACTION_ERASED, _NEIGHBOUR) == []


def test_erase_clears_every_linked_provisional_binding(datastore) -> None:
    # D10: merge_provisional_memory copies provisional slots from EVERY linked
    # channel identity onto the verified key on the next verified turn, so an
    # erase that stops at the verified binding is undone by the next message.
    driver, conn, _schema = datastore
    _link(conn, "sms", "+14165550101", _CUSTOMER)
    _link(conn, "email", "a@example.com", _CUSTOMER)
    _link(conn, "sms", "+14165559999", _NEIGHBOUR)

    identity = _verified_identity(channel="sms", channel_identity="+14165550101")
    _seed_all_four(driver, identity)
    for prov in ({"channel": "sms", "channel_identity": "+14165550101"},
                 {"channel": "email", "channel_identity": "a@example.com"},
                 {"channel": "sms", "channel_identity": "+14165559999"}):
        _ok(
            _run(
                driver,
                "upsert_preference",
                {"key": "channel_preference", "value": "sms"},
                identity=prov,
                user_id="acct_rep_1",
            )
        )
    assert _slots(conn, "provisional:sms:+14165550101") == {"channel_preference"}
    assert _slots(conn, "provisional:email:a@example.com") == {"channel_preference"}
    assert _slots(conn, "provisional:sms:+14165559999") == {"channel_preference"}

    erased = _ok(_erase(driver, identity))

    assert [b["binding_key"] for b in erased["bindings"]] == [
        _CUSTOMER,
        "provisional:sms:+14165550101",
        "provisional:email:a@example.com",
    ]
    assert _slots(conn, _CUSTOMER) == set()
    assert _slots(conn, "provisional:sms:+14165550101") == set()
    assert _slots(conn, "provisional:email:a@example.com") == set()
    # The OTHER customer's linked provisional binding is untouched -- the
    # enumeration is keyed on this customer, not on "every provisional row".
    assert _slots(conn, "provisional:sms:+14165559999") == {"channel_preference"}
    # D10: each cleared binding carries its own audit trail, not one lumped row.
    assert len(_audit(conn, MEMORY_ACTION_ERASED, "provisional:email:a@example.com")) == 1
    assert len(_audit(conn, "preference_cleared", "provisional:sms:+14165550101")) == 4


def test_erase_without_an_attributed_actor_is_policy_blocked_and_deletes_nothing(
    datastore,
) -> None:
    # ADR-0148 fail-closed, on the most destructive governed action in the
    # system. The second assertion is the load-bearing one: a gate that raised
    # AFTER the delete would still return policy_blocked.
    driver, conn, _schema = datastore
    _seed_all_four(driver, _verified_identity())

    result = _erase(driver, user_id=None)

    assert result.ok is False
    assert result.error_class == "policy_blocked"
    assert _slots(conn, _CUSTOMER) == set(MEMORY_PREFERENCE_SLOTS)
    assert _audit(conn, MEMORY_ACTION_ERASED, _CUSTOMER) == []
    assert _audit(conn, "preference_cleared", _CUSTOMER) == []


def test_erase_on_the_external_profile_is_blocked_even_for_a_verified_customer(
    datastore,
) -> None:
    # clear_preference authorizes a verified EXTERNAL customer clearing their own
    # slot and audits it with NO account_id (FR-21). The erase composes that gate
    # and then demands the actor its 4+1 rows are attributed to -- otherwise the
    # summary row would assert an erase with nobody attached (the D20 shape).
    driver, conn, _schema = datastore
    _seed_all_four(driver, _verified_identity())

    result = _erase(
        driver, user_id=None, profile="customer_service_external"
    )

    assert result.ok is False
    assert result.error_class == "policy_blocked"
    assert _slots(conn, _CUSTOMER) == set(MEMORY_PREFERENCE_SLOTS)


def test_erase_with_no_resolvable_identity_is_policy_blocked(datastore) -> None:
    # The shared binding resolver's own fail-closed raise (ADR-0112/FR-5), on
    # the erase path: no channel identity in context => policy_blocked, never a
    # shared bucket key an erase would then wipe for everybody on it.
    driver, _conn, _schema = datastore
    result = _run(
        driver, "erase_customer_memory", identity=None, user_id=_SUPERVISOR
    )
    assert result.ok is False
    assert result.error_class == "policy_blocked"


def test_erase_keeps_the_provenance_the_audit_trail_is_made_of(datastore) -> None:
    # The erase removes L4 CONTENT. It deliberately does not touch the two
    # provenance stores that also carry this binding key -- injection_ledger
    # (which slot NAME reached which turn; no value, by column list) and
    # customer_memory_merge_audit (7-year accountability). PAC-3 asks the erase
    # to leave a COMPLETE audit trail; deleting the trail would be the opposite,
    # and would silently break S10's blast-radius join. Pinned so a later
    # "while I'm here" tidy-up has to argue with a red test.
    driver, conn, _schema = datastore
    store = PostgresGatewayStore(connection=conn)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO customer_memory_slot "
            "(id, binding_key, binding_kind, slot_name, slot_value, source) "
            "VALUES ('mem_prov_1', 'provisional:sms:+14165550101', 'provisional', "
            "'channel_preference', 'sms', 'customer_explicit')"
        )
    conn.commit()
    store.merge_provisional_memory("provisional:sms:+14165550101", _CUSTOMER)
    store.record_injection_ledger(
        turn_ref="turn_1",
        case_or_binding_ref=_CUSTOMER,
        entries=[(LAYER_L4, f"{_CUSTOMER}:channel_preference")],
    )
    _seed_all_four(driver, _verified_identity())

    _ok(_erase(driver))

    assert _slots(conn, _CUSTOMER) == set()
    assert _rows(conn, "SELECT count(*) FROM customer_memory_merge_audit")[0][0] == 1
    assert (
        _rows(
            conn,
            "SELECT count(*) FROM injection_ledger WHERE entry_ref = %s",
            (f"{_CUSTOMER}:channel_preference",),
        )[0][0]
        == 1
    )


# --- FR-14: the deletion-success tripwire ------------------------------------


def test_a_clean_erase_scores_a_perfect_deletion_success_rate(datastore) -> None:
    driver, conn, _schema = datastore
    _seed_all_four(driver, _verified_identity())
    _ok(_erase(driver))

    with conn.cursor() as cur:
        metric = deletion_success_metric(cur)

    assert metric["window_days"] == ERASE_REAPPEARANCE_WINDOW_DAYS
    assert metric["erased_bindings"] == 1
    assert metric["flagged_bindings"] == 0
    assert metric["rate"] == 1.0
    assert metric["flagged_slots"] == {}


def test_the_tripwire_flags_a_row_the_erase_left_behind(datastore) -> None:
    # The whole point of FR-14: deletion REPORTED success and data survived.
    # The tripwire observes the STORE, so it cannot be satisfied by a return
    # value -- this row is inserted with a timestamp BEFORE the erase, so a
    # tripwire that only compared timestamps ("written after the erase") would
    # wave it through.
    driver, conn, _schema = datastore
    _seed_all_four(driver, _verified_identity())
    _ok(_erase(driver))
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO customer_memory_slot "
            "(id, binding_key, binding_kind, slot_name, slot_value, source, "
            " created_at, updated_at) "
            "VALUES ('mem_residue', %s, 'verified', 'delivery_habit_note', "
            "'leave at back door', 'customer_explicit', "
            "now() - interval '1 hour', now() - interval '1 hour')",
            (_CUSTOMER,),
        )
        conn.commit()

        metric = deletion_success_metric(cur)

    assert metric["erased_bindings"] == 1
    assert metric["flagged_bindings"] == 1
    assert metric["residue_bindings"] == 1
    assert metric["reappeared_bindings"] == 0
    assert metric["rate"] == 0.0
    assert metric["flagged_slots"] == {"delivery_habit_note": 1}


def test_the_tripwire_flags_a_slot_written_after_the_erase(datastore) -> None:
    driver, conn, _schema = datastore
    identity = _verified_identity()
    _seed_all_four(driver, identity)
    _ok(_erase(driver, identity))
    _ok(
        _run(
            driver,
            "upsert_preference",
            {"key": "contact_time_preference", "value": "after 2pm"},
            identity=identity,
            user_id="acct_rep_1",
        )
    )

    with conn.cursor() as cur:
        metric = deletion_success_metric(cur)

    assert metric["flagged_bindings"] == 1
    assert metric["reappeared_bindings"] == 1
    assert metric["residue_bindings"] == 0
    assert metric["flagged_slots"] == {"contact_time_preference": 1}


def test_a_post_erase_merge_restores_nothing_and_never_fires_the_alert(datastore) -> None:
    # D10 INVERTS S11's original acceptance. The brief as written required a
    # post-erase merge to fire the alert -- which would have made the alert a
    # permanent by-design false positive, because the merge would have restored
    # the slots the supervisor just erased. The erase clears the linked
    # provisional binding too, so the merge finds nothing and the tripwire stays
    # quiet: it now fires only on a genuinely unexpected write.
    driver, conn, _schema = datastore
    _link(conn, "sms", "+14165550101", _CUSTOMER)
    identity = _verified_identity(channel="sms", channel_identity="+14165550101")
    _seed_all_four(driver, identity)
    _ok(
        _run(
            driver,
            "upsert_preference",
            {"key": "delivery_habit_note", "value": "leave at back door"},
            identity={"channel": "sms", "channel_identity": "+14165550101"},
            user_id="acct_rep_1",
        )
    )
    assert _slots(conn, "provisional:sms:+14165550101") == {"delivery_habit_note"}

    _ok(_erase(driver, identity))

    merged = PostgresGatewayStore(connection=conn).merge_provisional_memory(
        "provisional:sms:+14165550101", _CUSTOMER
    )

    assert merged is None
    assert _slots(conn, _CUSTOMER) == set()
    with conn.cursor() as cur:
        metric = deletion_success_metric(cur)
    assert metric["flagged_bindings"] == 0
    assert metric["rate"] == 1.0


def test_a_second_erase_clears_the_flag_the_first_one_raised(datastore) -> None:
    # The anchor is MAX(created_at), so a binding is judged against its LATEST
    # erase. Without that, a supervisor who noticed the alert and re-erased
    # would be stuck looking at a permanent red flag raised by the write they
    # already dealt with -- and an alert that cannot be cleared stops being read.
    driver, conn, _schema = datastore
    identity = _verified_identity()
    _seed_all_four(driver, identity)
    _ok(_erase(driver, identity))
    _ok(
        _run(
            driver,
            "upsert_preference",
            {"key": "contact_time_preference", "value": "after 2pm"},
            identity=identity,
            user_id="acct_rep_1",
        )
    )
    with conn.cursor() as cur:
        assert deletion_success_metric(cur)["flagged_bindings"] == 1

    _ok(_erase(driver, identity))

    with conn.cursor() as cur:
        metric = deletion_success_metric(cur)
    assert metric["erased_bindings"] == 1
    assert metric["flagged_bindings"] == 0
    assert metric["rate"] == 1.0


def test_the_tripwire_ignores_an_erase_older_than_the_window(datastore) -> None:
    # N is a real bound, not decoration: a customer who states a preference
    # again months after an erase is not an incident.
    driver, conn, _schema = datastore
    identity = _verified_identity()
    _seed_all_four(driver, identity)
    _ok(_erase(driver, identity))
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE workbench_audit_log SET created_at = now() - "
            "make_interval(days => %s) WHERE action = %s",
            (ERASE_REAPPEARANCE_WINDOW_DAYS + 1, MEMORY_ACTION_ERASED),
        )
        conn.commit()
    _ok(
        _run(
            driver,
            "upsert_preference",
            {"key": "contact_time_preference", "value": "after 2pm"},
            identity=identity,
            user_id="acct_rep_1",
        )
    )

    with conn.cursor() as cur:
        metric = deletion_success_metric(cur)

    assert metric["erased_bindings"] == 0
    assert metric["flagged_bindings"] == 0
    assert metric["rate"] is None


def test_the_tripwire_ignores_a_binding_that_was_never_erased(datastore) -> None:
    driver, conn, _schema = datastore
    _seed_all_four(driver, _verified_identity(_NEIGHBOUR))
    _seed_all_four(driver, _verified_identity())
    _ok(_erase(driver))
    assert _slots(conn, _NEIGHBOUR) == set(MEMORY_PREFERENCE_SLOTS)

    with conn.cursor() as cur:
        metric = deletion_success_metric(cur)

    assert metric["erased_bindings"] == 1
    assert metric["flagged_bindings"] == 0


def test_deletion_success_rides_the_aggregate_metrics_payload(datastore) -> None:
    # S22 places the tile; this slice's job is that the number is THERE for it,
    # on the same admin read the rest of FR-28's panel comes from.
    driver, _conn, _schema = datastore
    _seed_all_four(driver, _verified_identity())
    _ok(_erase(driver))

    metrics = _ok(
        execute_tool(
            tool="toee_metrics",
            action="get_aggregate_metrics",
            params={},
            context=ToolExecutionContext(profile="internal_copilot"),
            driver=driver,
        )
    )

    assert metrics["deletion_success"]["erased_bindings"] == 1
    assert metrics["deletion_success"]["rate"] == 1.0


def test_the_mock_twin_reports_the_same_empty_deletion_success_payload() -> None:
    # NFR-7. The two twins share the payload BUILDER rather than restating it
    # (one better than latency's pinned restatement), so this asserts the mock
    # actually calls it -- a missing key would break S22's panel under
    # TOOL_BACKEND=mock, and no Postgres test could see that.
    from toee_hermes.drivers.mock.metrics import create_metrics_mock_handlers

    handlers = create_metrics_mock_handlers()
    payload = handlers["toee_metrics"]["get_aggregate_metrics"]({}, None)

    assert payload["deletion_success"] == deletion_success_payload()
