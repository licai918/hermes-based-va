"""S07: turn-time Customer Memory read injection on the external turn (FR-1, R2).

The KEY round-trip proof: a preference WRITTEN through the governed datastore path
(which derives its binding key via ``resolve_customer_memory_binding``) is injected
into a *subsequent* ``run_turn`` for the same identity — proving the turn-time READ
derives a byte-identical binding key via the SAME shared core
(``binding_key_from_identity``). If the two derivations ever drift, the round-trip
silently returns nothing and these tests fail.

Real Postgres via the shared ``datastore`` fixture (skip-if-no-DB); the model is
the scripted provider, and ``run_agent_turn`` is captured so the assertion is on the
exact injected user message (R2 content round-trip), not a model reply.
"""

from __future__ import annotations

from types import SimpleNamespace

from toee_hermes.execute import execute_tool
from toee_hermes.gateway.ingress import SessionIdentitySnapshot
from toee_hermes.plugin.profiles import EXTERNAL
from toee_hermes.tool_gate import ToolExecutionContext

from hermes_runtime.live import _scripted_openai_factory
from hermes_runtime.openrouter import (
    OPENROUTER_PRIMARY_MODEL,
    OpenRouterConfig,
    make_openrouter_run_turn,
)
from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

_CONFIG = OpenRouterConfig(
    base_url="https://openrouter.ai/api/v1",
    api_key="sk-or-test",
    model=OPENROUTER_PRIMARY_MODEL,
)

_SHOPIFY_ID = "gid://shopify/Customer/70701"
_VERIFIED_PREF = "text me after 5pm, don't call"
_PROVISIONAL_PHONE = "+14165550175"
_PROVISIONAL_PREF = "leave orders at the loading dock"


class _ExplodingStore:
    """A store whose read must never run (gate/fail-closed guard)."""

    def load_customer_memory(self, binding_key):  # pragma: no cover - must not run
        raise AssertionError(
            f"load_customer_memory must not be called (binding_key={binding_key!r})"
        )


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


def _run_turn_capturing_injection(monkeypatch, *, store, context, inbound_body="Hi again"):
    """Build ``run_turn`` with the injected store; return the injected user message.

    ``run_agent_turn`` is stubbed — the injection (read + shared binding derivation)
    runs for real, but no agent loop / network does, so the assertion is on the
    exact prompt handed to the model.
    """
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
    run_turn(context, inbound_body)
    return captured["user_message"]


def test_verified_turn_injects_the_stored_preference_round_trip(datastore, monkeypatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    driver, conn, _ = datastore
    _write_preference(
        driver,
        identity={"outcome": "verified_customer", "shopify_customer_id": _SHOPIFY_ID},
        key="contact_time_preference",
        value=_VERIFIED_PREF,
    )

    context = SimpleNamespace(
        conversation_id="conv-mem-verified",
        sms_session_id=None,
        # A different phone than any write: verified binds on the Shopify id, so
        # the round-trip must still hit the same key regardless of channel identity.
        from_phone="+14165559999",
        session_identity_snapshot=SessionIdentitySnapshot(
            outcome="verified_customer",
            resolved_at="2026-07-13T00:00:00Z",
            shopify_customer_id=_SHOPIFY_ID,
            display_name="Round Trip Co",
        ),
    )

    user_message = _run_turn_capturing_injection(
        monkeypatch, store=PostgresGatewayStore(connection=conn), context=context
    )

    assert "Customer Memory (preferences):" in user_message
    assert _VERIFIED_PREF in user_message


def test_provisional_turn_injects_the_stored_preference_round_trip(datastore, monkeypatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    driver, conn, _ = datastore
    _write_preference(
        driver,
        identity={"channel": "sms", "channel_identity": _PROVISIONAL_PHONE},
        key="delivery_habit_note",
        value=_PROVISIONAL_PREF,
    )

    context = SimpleNamespace(
        conversation_id="conv-mem-provisional",
        sms_session_id=None,
        from_phone=_PROVISIONAL_PHONE,  # unmatched caller -> provisional binding
        session_identity_snapshot=None,
    )

    user_message = _run_turn_capturing_injection(
        monkeypatch, store=PostgresGatewayStore(connection=conn), context=context
    )

    assert "Customer Memory (preferences):" in user_message
    assert _PROVISIONAL_PREF in user_message


def test_memory_disabled_injects_no_memory_block(monkeypatch) -> None:
    # S05/FR-7: TOOL_BACKEND unset -> memory_enabled() False -> the read is never
    # attempted (the store raises if touched) and no memory block is injected; the
    # turn still completes normally.
    monkeypatch.delenv("TOOL_BACKEND", raising=False)

    context = SimpleNamespace(
        conversation_id="conv-mem-off",
        sms_session_id=None,
        from_phone=_PROVISIONAL_PHONE,
        session_identity_snapshot=None,
    )

    user_message = _run_turn_capturing_injection(
        monkeypatch, store=_ExplodingStore(), context=context
    )

    assert "Customer Memory" not in user_message


def test_unresolvable_binding_injects_no_memory_block_without_raising(monkeypatch) -> None:
    # Read fail-closed: memory enabled but no resolvable channel identity (a phone
    # that normalizes to a bare "+") -> inject nothing, never raise (contrast the
    # write tool, which raises policy_blocked).
    monkeypatch.setenv("TOOL_BACKEND", "datastore")

    context = SimpleNamespace(
        conversation_id="conv-mem-nobinding",
        sms_session_id=None,
        from_phone="no digits here",  # normalize_e164 -> "+", degenerate
        session_identity_snapshot=None,
    )

    user_message = _run_turn_capturing_injection(
        monkeypatch, store=_ExplodingStore(), context=context
    )

    assert "Customer Memory" not in user_message
