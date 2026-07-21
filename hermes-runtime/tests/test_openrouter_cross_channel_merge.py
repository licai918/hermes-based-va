"""S19 / FR-19 / ADR-0151: cross-channel provisional merge — precedence + live-PG proof.

Generalizes the S10 single-channel merge (``test_openrouter_provisional_merge.py``):
a verified turn on ONE channel must also pull provisional slots stated on every
OTHER channel identity linked to the same verified customer (``identity_link``),
not just the current turn's own channel. The merge unit of work
(``PostgresGatewayStore.merge_provisional_memory``) is unchanged — it is called
once per linked source key, in a deterministic precedence order (ADR-0151):

    1. THIS turn's own channel (the freshest, just-stated signal)
    2. every other channel identity linked to the same verified customer, in a
       fixed ``(channel, channel_identity)`` order

Because the merge unit's ``ON CONFLICT (binding_key, slot_name) DO NOTHING`` lets
the FIRST writer of an empty verified slot win, this call order IS the precedence
for a slot name stated on more than one linked channel. Verified slots are still
NEVER overwritten (ADR-0112) regardless of source count.

Fixtures reuse the SAME phone/email/shopify id the mock identity baseline maps to
Customer/1001 (``hermes/toee_hermes/drivers/mock/identity.py``), per the S19 brief
— not because these tests touch the mock driver (they exercise the real Postgres
``identity_link`` table + the live merge path).
"""

from __future__ import annotations

from types import SimpleNamespace

from toee_hermes.execute import execute_tool
from toee_hermes.gateway.ingress import SessionIdentitySnapshot
from toee_hermes.gateway.normalize import SIMULATED_EMAIL, canonicalize_email, normalize_e164
from toee_hermes.plugin.profiles import EXTERNAL
from toee_hermes.tool_gate import ToolExecutionContext

from hermes_runtime.live import _scripted_openai_factory
from hermes_runtime.openrouter import (
    OPENROUTER_PRIMARY_MODEL,
    OpenRouterConfig,
    _merge_provisional_memory,
    make_openrouter_run_turn,
)
from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

_CONFIG = OpenRouterConfig(
    base_url="https://openrouter.ai/api/v1",
    api_key="sk-or-test",
    model=OPENROUTER_PRIMARY_MODEL,
)

# Same triple the mock identity baseline maps to Customer/1001 -- reused here so
# fixtures stay consistent across the mock and live-Postgres test suites.
_SHOPIFY_ID = "gid://shopify/Customer/1001"
_PHONE = "+14165550101"
_EMAIL = "accounts@acme-fleet.example"
_SMS_PREF = "leave orders at the loading dock"


# --------------------------------------------------------------------------
# Precedence unit tests: pure Python, no Postgres -- prove the ORDER
# `_merge_provisional_memory` calls `merge_provisional_memory` in.
# --------------------------------------------------------------------------


class _FakeLinkedStore:
    """Records merge-call order; backs `list_channel_identities_for_customer`
    with an injectable table. No DB -- these tests are about precedence
    ordering, not the SQL merge unit (already proven store-side)."""

    def __init__(self, linked=None, raise_for=frozenset()):
        self._linked = linked or {}  # {verified_key: [(channel, channel_identity), ...]}
        self._raise_for = raise_for  # provisional keys whose merge call raises
        self.calls: list[tuple[str, str]] = []

    def list_channel_identities_for_customer(self, shopify_customer_id):
        return self._linked.get(shopify_customer_id, [])

    def merge_provisional_memory(self, provisional_key, verified_key):
        self.calls.append((provisional_key, verified_key))
        if provisional_key in self._raise_for:
            raise RuntimeError("merge boom")
        return {"moved": ["some_slot"], "overridden": {}}


def _email_identity() -> dict[str, object]:
    return {
        "outcome": "verified_customer",
        "shopify_customer_id": _SHOPIFY_ID,
        "channel": "email",
        "channel_identity": canonicalize_email(_EMAIL),
    }


def test_own_channel_merges_before_other_linked_channels(monkeypatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    store = _FakeLinkedStore({_SHOPIFY_ID: [("sms", _PHONE), ("email", _EMAIL)]})

    fired = _merge_provisional_memory(_email_identity(), store)

    assert fired is True
    assert store.calls == [
        (f"provisional:email:{canonicalize_email(_EMAIL)}", _SHOPIFY_ID),
        (f"provisional:sms:{normalize_e164(_PHONE)}", _SHOPIFY_ID),
    ]


def test_dedups_own_channel_against_the_linked_list(monkeypatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    # The customer's own (current-turn) channel is also present in identity_link
    # (a prior match already linked it) -- must merge exactly once, not twice.
    store = _FakeLinkedStore({_SHOPIFY_ID: [("email", _EMAIL)]})

    _merge_provisional_memory(_email_identity(), store)

    assert store.calls == [(f"provisional:email:{canonicalize_email(_EMAIL)}", _SHOPIFY_ID)]


def test_remaining_linked_channels_ordered_deterministically(monkeypatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    # Two OTHER linked phones (beyond the current email turn): order is fixed
    # (channel, channel_identity) ascending -- the contract
    # PostgresGatewayStore.list_channel_identities_for_customer's own ORDER BY
    # already guarantees, mirrored here so identical inputs always produce
    # identical merge-call order (ADR-0151).
    store = _FakeLinkedStore(
        {_SHOPIFY_ID: [("sms", "+14165550111"), ("sms", "+14165550999")]}
    )

    _merge_provisional_memory(_email_identity(), store)

    assert [key for key, _ in store.calls] == [
        f"provisional:email:{canonicalize_email(_EMAIL)}",
        f"provisional:sms:{normalize_e164('+14165550111')}",
        f"provisional:sms:{normalize_e164('+14165550999')}",
    ]


def test_no_linked_channels_still_merges_the_current_channel(monkeypatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    # 1-element case: no other linked channels -- behaves exactly like pre-S19.
    store = _FakeLinkedStore({})

    fired = _merge_provisional_memory(_email_identity(), store)

    assert fired is True
    assert store.calls == [(f"provisional:email:{canonicalize_email(_EMAIL)}", _SHOPIFY_ID)]


def test_a_store_without_the_new_method_degrades_to_single_channel_merge(monkeypatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    # Pre-S19 test doubles across the suite don't implement
    # list_channel_identities_for_customer -- must not raise, must still merge
    # this turn's own channel (backward compatible).
    class _LegacyStore:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def merge_provisional_memory(self, provisional_key, verified_key):
            self.calls.append((provisional_key, verified_key))
            return {"moved": ["some_slot"], "overridden": {}}

    store = _LegacyStore()

    fired = _merge_provisional_memory(_email_identity(), store)

    assert fired is True
    assert store.calls == [(f"provisional:email:{canonicalize_email(_EMAIL)}", _SHOPIFY_ID)]


def test_one_linked_channels_merge_failure_does_not_abort_the_others(monkeypatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    # FR-7: a hiccup merging ONE source key must not prevent the others from
    # merging this turn (each source is independently idempotent/retryable).
    store = _FakeLinkedStore(
        {_SHOPIFY_ID: [("sms", _PHONE)]},
        raise_for={f"provisional:sms:{normalize_e164(_PHONE)}"},
    )

    fired = _merge_provisional_memory(_email_identity(), store)

    assert fired is True  # the email (own-channel) merge still succeeded
    assert store.calls == [
        (f"provisional:email:{canonicalize_email(_EMAIL)}", _SHOPIFY_ID),
        (f"provisional:sms:{normalize_e164(_PHONE)}", _SHOPIFY_ID),
    ]


# --------------------------------------------------------------------------
# Live-Postgres integration: the SMS -> email continuity path (FR-19's headline
# scenario), the real `identity_link` table, the real merge SQL, real audit rows.
# --------------------------------------------------------------------------


def _link(conn, *, channel, channel_identity, shopify_customer_id) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO identity_link
                (id, channel, channel_identity, shopify_customer_id, match_status)
            VALUES (%s, %s, %s, %s, 'verified')
            """,
            (f"idl_{channel}_{channel_identity}", channel, channel_identity, shopify_customer_id),
        )
    conn.commit()


def _write_provisional(driver, *, phone, key, value):
    result = execute_tool(
        tool="toee_customer_memory",
        action="upsert_preference",
        params={"key": key, "value": value},
        context=ToolExecutionContext(
            profile=EXTERNAL, identity={"channel": "sms", "channel_identity": phone}
        ),
        driver=driver,
    )
    assert result.ok, result
    return result.data["binding_key"]


def _run_email_turn(monkeypatch, *, store) -> str:
    import hermes_runtime.openrouter as openrouter_mod

    captured: dict[str, str] = {}

    def capture(*, user_message: str, **_kwargs: object) -> dict[str, object]:
        captured["user_message"] = user_message
        return {"final_response": "", "messages": []}

    monkeypatch.setattr(openrouter_mod, "run_agent_turn", capture)
    run_turn = make_openrouter_run_turn(
        config=_CONFIG,
        openai_factory=_scripted_openai_factory([{"content": "ok"}]),
        store=store,
    )
    context = SimpleNamespace(
        conversation_id="conv-cross-channel",
        sms_session_id=None,
        from_phone=_EMAIL,
        session_identity_snapshot=SessionIdentitySnapshot(
            outcome="verified_customer",
            resolved_at="2026-07-20T00:00:00Z",
            shopify_customer_id=_SHOPIFY_ID,
            display_name="Acme Fleet",
        ),
        channel=SIMULATED_EMAIL,
    )
    run_turn(context, "Any update on my order?")
    return captured["user_message"]


def _audit_rows(cur, verified_key):
    cur.execute(
        "SELECT provisional_key FROM customer_memory_merge_audit WHERE verified_key = %s",
        (verified_key,),
    )
    return {row[0] for row in cur.fetchall()}


def test_verified_email_turn_pulls_the_linked_sms_provisional_too(datastore, monkeypatch) -> None:
    """FR-19 headline scenario: a preference stated over SMS is honored in a LATER
    verified email conversation once the identities are linked to the same
    customer -- SMS->email continuity, same turn (PAC-3)."""
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    driver, conn, _ = datastore
    prov_sms_key = _write_provisional(
        driver, phone=_PHONE, key="delivery_habit_note", value=_SMS_PREF
    )
    assert prov_sms_key == f"provisional:sms:{normalize_e164(_PHONE)}"
    _link(conn, channel="sms", channel_identity=normalize_e164(_PHONE), shopify_customer_id=_SHOPIFY_ID)
    _link(conn, channel="email", channel_identity=_EMAIL, shopify_customer_id=_SHOPIFY_ID)

    user_message = _run_email_turn(monkeypatch, store=PostgresGatewayStore(connection=conn))

    with conn.cursor() as cur:
        # the sms provisional migrated onto the verified customer...
        cur.execute(
            "SELECT slot_value, source FROM customer_memory_slot "
            "WHERE binding_key = %s AND slot_name = 'delivery_habit_note'",
            (_SHOPIFY_ID,),
        )
        assert cur.fetchone() == (_SMS_PREF, "merged_provisional")
        # ...and its provisional copy is gone
        cur.execute(
            "SELECT count(*) FROM customer_memory_slot WHERE binding_key = %s", (prov_sms_key,)
        )
        assert cur.fetchone()[0] == 0
        # one audit row for the sms source (the email channel had nothing to merge)
        assert _audit_rows(cur, _SHOPIFY_ID) == {prov_sms_key}

    # the merge ran before the read -> honored in THIS same email turn
    assert _SMS_PREF in user_message


def test_verified_slot_is_never_overwritten_by_either_linked_channel(datastore, monkeypatch) -> None:
    """ADR-0112 invariant, cross-channel case: an already-verified slot value
    survives a merge even when BOTH linked channels carry a conflicting
    provisional value for the same slot name."""
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    driver, conn, _ = datastore
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO customer_memory_slot
                (id, binding_key, binding_kind, slot_name, slot_value, source)
            VALUES (%s, %s, 'verified', 'channel_preference', 'sms', 'customer_explicit')
            """,
            (f"mem_{_SHOPIFY_ID}_channel_preference", _SHOPIFY_ID),
        )
    conn.commit()
    _write_provisional(driver, phone=_PHONE, key="channel_preference", value="email")
    _link(conn, channel="sms", channel_identity=normalize_e164(_PHONE), shopify_customer_id=_SHOPIFY_ID)
    _link(conn, channel="email", channel_identity=_EMAIL, shopify_customer_id=_SHOPIFY_ID)

    _run_email_turn(monkeypatch, store=PostgresGatewayStore(connection=conn))

    with conn.cursor() as cur:
        cur.execute(
            "SELECT slot_value, source FROM customer_memory_slot "
            "WHERE binding_key = %s AND slot_name = 'channel_preference'",
            (_SHOPIFY_ID,),
        )
        # verified value untouched -- never overwritten by the provisional
        assert cur.fetchone() == ("sms", "customer_explicit")
        cur.execute(
            "SELECT details FROM customer_memory_merge_audit "
            "WHERE verified_key = %s AND provisional_key = %s",
            (_SHOPIFY_ID, f"provisional:sms:{normalize_e164(_PHONE)}"),
        )
        (details,) = cur.fetchone()
        assert details["overridden"] == {"channel_preference": "email"}


def test_removal_tripwire_still_green_alongside_cross_channel_merge(datastore) -> None:
    """Sanity companion to the S19 brief's removal-tripwire requirement: proves
    the cross-channel change doesn't touch `list_channel_identities_for_customer`
    for an UNLINKED customer -- it returns empty, no phantom merges."""
    _, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    assert store.list_channel_identities_for_customer("gid://shopify/Customer/999999") == []
