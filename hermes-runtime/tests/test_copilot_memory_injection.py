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

from toee_hermes.execute import execute_tool
from toee_hermes.plugin.profiles import EXTERNAL
from toee_hermes.tool_gate import ToolExecutionContext

from hermes_runtime.copilot_turn import make_copilot_run_turn
from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

_SHOPIFY_ID = "gid://shopify/Customer/70701"
_VERIFIED_PREF = "text me after 5pm, don't call"
_PROVISIONAL_PHONE = "+14165550175"
_PROVISIONAL_PREF = "leave orders at the loading dock"


class _ExplodingStore:
    """A store whose reads must never run (gate/fail-closed guard)."""

    def load_case_identity(self, case_id):  # pragma: no cover - must not run
        raise AssertionError(f"load_case_identity must not be called (case_id={case_id!r})")

    def load_customer_memory(self, binding_key):  # pragma: no cover - must not run
        raise AssertionError(
            f"load_customer_memory must not be called (binding_key={binding_key!r})"
        )


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
    # S05/FR-7: TOOL_BACKEND unset -> memory_enabled() False -> neither the
    # case->thread lookup nor the memory read is attempted (the store raises if
    # touched) and no block is injected; the draft turn still completes normally.
    monkeypatch.delenv("TOOL_BACKEND", raising=False)

    user_message = _run_copilot_capturing_injection(
        monkeypatch, store=_ExplodingStore(), case_id="case-x"
    )

    assert "Customer Memory" not in user_message


def test_copilot_turn_for_an_unknown_case_injects_no_block(datastore, monkeypatch) -> None:
    # Read fail-closed: memory enabled but the case has no thread to bind (here: the
    # case does not exist at all) -> inject nothing, never raise.
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    _driver, conn, _ = datastore

    user_message = _run_copilot_capturing_injection(
        monkeypatch, store=PostgresGatewayStore(connection=conn), case_id="case-does-not-exist"
    )

    assert "Customer Memory" not in user_message
