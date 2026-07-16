"""S08: turn-time Customer Memory read injection on the Copilot draft turn (FR-1, R2).

The Copilot draft seam (``make_copilot_run_turn``) is bound to a ``case_id``, not a
phone, so its binding key is derived from the case's ``customer_thread`` identity —
a SEPARATE seam from the external turn (S07). This proves the round-trip: a
preference WRITTEN through the governed datastore path (which derives its key via
``resolve_customer_memory_binding``) is injected into a Copilot draft turn opened
for a case whose thread resolves to the SAME identity, via the SAME shared core
``binding_key_from_identity``. Isolation: a different case/customer never sees
another's block. No stored slots / memory disabled -> no block, never a raise.

Real Postgres via the shared ``datastore`` fixture (skip-if-no-DB); the model loop
is stubbed so the assertion is on the exact injected user message (R2 content
round-trip), and the test is order-independent (no global registry dispatch).
"""

from __future__ import annotations

import logging

from toee_hermes.execute import execute_tool
from toee_hermes.plugin.profiles import EXTERNAL
from toee_hermes.tool_gate import ToolExecutionContext

from hermes_runtime.copilot_turn import _load_case_memory, make_copilot_run_turn
from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

_SHOPIFY_ID = "gid://shopify/Customer/70701"
_VERIFIED_PREF = "text me after 5pm, don't call"
_PROVISIONAL_PHONE = "+14165550175"
_PROVISIONAL_PREF = "leave orders at the loading dock"


class _ReadRaisingStore:
    """Case identity resolves fine; the memory read itself explodes (S11 parity)."""

    def load_case_identity(self, case_id):
        return {"outcome": "verified_customer", "shopify_customer_id": _SHOPIFY_ID}

    def load_customer_memory(self, binding_key):
        raise RuntimeError("read boom")


class _IdentityRaisingStore:
    """The case->thread identity lookup itself explodes (S10, S11-parity sibling).

    The exception message stands in for a store leak (e.g. driver-echoed customer
    content) -- it must never reach the log, only the exception's TYPE.
    """

    def load_case_identity(self, case_id):
        raise RuntimeError("identity boom -- must never appear in logs")

    def load_customer_memory(self, binding_key):  # pragma: no cover - must not run
        raise AssertionError("load_customer_memory must not run when identity lookup failed")


def _seed_case(
    conn,
    *,
    case_id,
    thread_id,
    channel_identity,
    channel="sms",
    shopify_customer_id=None,
):
    """Seed a customer_thread + an open case bound to it (the case->thread lookup input)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO customer_thread (id, channel, channel_identity, shopify_customer_id)"
            " VALUES (%s, %s, %s, %s)",
            (thread_id, channel, channel_identity, shopify_customer_id),
        )
        cur.execute(
            "INSERT INTO cases (id, channel, customer_thread_id) VALUES (%s, %s, %s)",
            (case_id, channel, thread_id),
        )
    conn.commit()


def _write_preference(driver, *, identity, key, value):
    """Store a preference through the real governed write path (S02/S03 binding)."""
    result = execute_tool(
        tool="toee_customer_memory",
        action="upsert_preference",
        params={"key": key, "value": value},
        context=ToolExecutionContext(profile=EXTERNAL, identity=identity),
        driver=driver,
    )
    assert result.ok, result
    return result


def _run_copilot_capturing_injection(monkeypatch, *, store, case_id, channel="sms"):
    """Run a Copilot draft turn with the injected store; return the injected user message.

    ``run_scripted_agent`` is stubbed — the case->thread identity resolution, the
    memory read, and the shared binding derivation run for real, but no agent loop
    (and so no global-registry dispatch) does, so the assertion is on the exact
    prompt handed to the model.
    """
    import hermes_runtime.copilot_turn as copilot_mod

    captured: dict[str, str] = {}

    def capture(*, user_message: str, **_kwargs: object) -> dict[str, object]:
        captured["user_message"] = user_message
        return {"final_response": "", "messages": []}

    monkeypatch.setattr(copilot_mod, "run_scripted_agent", capture)
    run_turn = make_copilot_run_turn(
        scripted_completions=[{"content": "ok"}], store=store
    )
    run_turn(channel=channel, case_id=case_id)
    return captured["user_message"]


def test_copilot_turn_injects_stored_preference_for_a_verified_case(datastore, monkeypatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    driver, conn, _ = datastore
    _seed_case(
        conn,
        case_id="case-mem-verified",
        thread_id="thr-verified",
        channel_identity="+14165550111",
        shopify_customer_id=_SHOPIFY_ID,
    )
    _write_preference(
        driver,
        identity={"outcome": "verified_customer", "shopify_customer_id": _SHOPIFY_ID},
        key="contact_time_preference",
        value=_VERIFIED_PREF,
    )

    user_message = _run_copilot_capturing_injection(
        monkeypatch,
        store=PostgresGatewayStore(connection=conn),
        case_id="case-mem-verified",
    )

    assert "Customer Memory (preferences):" in user_message
    assert _VERIFIED_PREF in user_message


def test_copilot_turn_injects_provisional_preference_round_trip(datastore, monkeypatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    driver, conn, _ = datastore
    _seed_case(
        conn,
        case_id="case-mem-provisional",
        thread_id="thr-provisional",
        channel_identity=_PROVISIONAL_PHONE,
        shopify_customer_id=None,  # unmatched caller -> provisional binding on the thread
    )
    _write_preference(
        driver,
        identity={"channel": "sms", "channel_identity": _PROVISIONAL_PHONE},
        key="delivery_habit_note",
        value=_PROVISIONAL_PREF,
    )

    user_message = _run_copilot_capturing_injection(
        monkeypatch,
        store=PostgresGatewayStore(connection=conn),
        case_id="case-mem-provisional",
    )

    assert "Customer Memory (preferences):" in user_message
    assert _PROVISIONAL_PREF in user_message


def test_copilot_turn_never_sees_another_customers_block(datastore, monkeypatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    driver, conn, _ = datastore
    # Customer A has a stored preference.
    _seed_case(
        conn,
        case_id="case-A",
        thread_id="thr-A",
        channel_identity="+14165550111",
        shopify_customer_id=_SHOPIFY_ID,
    )
    _write_preference(
        driver,
        identity={"outcome": "verified_customer", "shopify_customer_id": _SHOPIFY_ID},
        key="contact_time_preference",
        value=_VERIFIED_PREF,
    )
    # Customer B (different thread + Shopify id) has its OWN distinct preference.
    other_id = "gid://shopify/Customer/80802"
    other_pref = "call the front desk, not my cell"
    _seed_case(
        conn,
        case_id="case-B",
        thread_id="thr-B",
        channel_identity="+14165550222",
        shopify_customer_id=other_id,
    )
    _write_preference(
        driver,
        identity={"outcome": "verified_customer", "shopify_customer_id": other_id},
        key="contact_time_preference",
        value=other_pref,
    )

    # Opening B's case injects B's preference and NEVER A's.
    user_message = _run_copilot_capturing_injection(
        monkeypatch, store=PostgresGatewayStore(connection=conn), case_id="case-B"
    )

    assert other_pref in user_message
    assert _VERIFIED_PREF not in user_message


def test_copilot_turn_with_no_stored_slots_injects_no_block(datastore, monkeypatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    _driver, conn, _ = datastore
    _seed_case(
        conn,
        case_id="case-empty",
        thread_id="thr-empty",
        channel_identity="+14165550333",
        shopify_customer_id=None,
    )

    user_message = _run_copilot_capturing_injection(
        monkeypatch, store=PostgresGatewayStore(connection=conn), case_id="case-empty"
    )

    assert "Customer Memory" not in user_message


def test_copilot_memory_disabled_injects_no_block(monkeypatch) -> None:
    # S05/FR-7: TOOL_BACKEND unset -> memory_enabled() False. The genuine
    # no-datastore turn has no store to resolve from, so _load_case_memory dials
    # nothing -- neither identity nor memory -- and no block is injected; the draft
    # still completes. (task_86123a78 decoupled identity from the memory gate, so a
    # PROVIDED store IS now consulted for identity for business-tool reads; the no-DB
    # contract is precisely that there is no store to consult -- the gateway store is
    # dialed only when memory is enabled, never reaching for a datastore that is off.)
    monkeypatch.delenv("TOOL_BACKEND", raising=False)

    # Hardening: with no store + memory off, the gateway store must NEVER be dialed
    # (a black-holed live datastore has hung this project for hours). Fail fast in
    # milliseconds if a future change ever reaches for it on this path.
    import hermes_runtime.copilot_turn as copilot_mod

    def _must_not_dial():
        raise AssertionError("_gateway_store must not be dialed when memory is disabled")

    monkeypatch.setattr(copilot_mod, "_gateway_store", _must_not_dial)

    user_message = _run_copilot_capturing_injection(
        monkeypatch, store=None, case_id="case-x"
    )

    assert "Customer Memory" not in user_message


def test_copilot_memory_disabled_still_resolves_case_identity(monkeypatch) -> None:
    # task_86123a78 regression: business-tool reads (get_order/get_delivery_status/
    # QBO) verify against context.identity, so a verified case must resolve its
    # identity even when Customer Memory slots are disabled. Before the fix this
    # returned (None, None) -> the draft agent could not read a verified customer's
    # own data. Identity is decoupled from the memory gate; only the SLOTS load is
    # gated (load_customer_memory must not run when memory is off).
    monkeypatch.delenv("TOOL_BACKEND", raising=False)  # memory_enabled() -> False

    verified = {
        "outcome": "verified_customer",
        "shopify_customer_id": "gid://shopify/Customer/1001",
    }

    class _VerifiedIdentityStore:
        def load_case_identity(self, case_id):
            return verified

        def load_customer_memory(self, binding_key):  # pragma: no cover - must not run
            raise AssertionError("memory slots must not load when memory is disabled")

    identity, memory = _load_case_memory("case-verified", _VerifiedIdentityStore())

    assert identity == verified  # resolved for business-tool verification
    assert memory is None  # slots gated by memory_enabled()


def test_copilot_turn_for_an_unknown_case_injects_no_block(datastore, monkeypatch) -> None:
    # Read fail-closed: memory enabled but the case has no thread to bind (here: the
    # case does not exist at all) -> inject nothing, never raise.
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    _driver, conn, _ = datastore

    user_message = _run_copilot_capturing_injection(
        monkeypatch, store=PostgresGatewayStore(connection=conn), case_id="case-does-not-exist"
    )

    assert "Customer Memory" not in user_message


def test_copilot_memory_read_error_logs_warning_and_turn_still_completes(
    monkeypatch, caplog
) -> None:
    # Parity with openrouter.py's _load_turn_memory (S11): a store-read error must
    # not swallow silently -- WARN, then degrade to no memory injected (FR-7).
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    caplog.set_level(logging.WARNING)

    user_message = _run_copilot_capturing_injection(
        monkeypatch, store=_ReadRaisingStore(), case_id="case-mem-read-error"
    )

    assert "Customer Memory" not in user_message

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "read" in warnings[0].getMessage().lower()


def test_copilot_case_identity_lookup_error_logs_warning_and_turn_still_completes(
    monkeypatch, caplog
) -> None:
    # S10 (FR-8), sibling to the S11 read-failure test above: the OTHER swallow in
    # _load_case_memory -- load_case_identity itself raising -- must not be silent
    # either. WARN, then degrade to no memory injected (no behaviour change, NFR-4).
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    caplog.set_level(logging.WARNING)

    user_message = _run_copilot_capturing_injection(
        monkeypatch, store=_IdentityRaisingStore(), case_id="case-mem-identity-error"
    )

    assert "Customer Memory" not in user_message  # degrades cleanly -- unchanged

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "identity" in message.lower()
    assert "RuntimeError" in message  # the exception TYPE
    assert "case-mem-identity-error" in message  # case_id: an internal id, not PII
    assert "identity boom" not in message  # never str(exc) -- could echo store content
