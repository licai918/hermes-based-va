"""S10 / FR-4: the provisional->verified merge fires on the async turn (run_turn).

The merge trigger lives on the ASYNC agent-turn path (``make_openrouter_run_turn``),
never the synchronous webhook ack (RK-5). These tests drive ``run_turn`` with a
stubbed ``run_agent_turn`` (no network) against real Postgres (throwaway-schema
``datastore`` fixture) and assert the merge happened in the datastore:

- a verified turn merges the caller's pre-verification provisional slots onto the
  verified record, deletes the provisional copies, and -- because the merge runs
  before the turn-time read -- injects the just-merged preference on the SAME turn;
- an ambiguous or unmatched turn never merges;
- a disabled backend (TOOL_BACKEND unset) never touches the store.
"""

from __future__ import annotations

from types import SimpleNamespace

from toee_hermes.execute import execute_tool
from toee_hermes.gateway.ingress import SessionIdentitySnapshot
from toee_hermes.gateway.normalize import normalize_e164
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

_SHOPIFY_ID = "gid://shopify/Customer/80808"
_PHONE = "+14165550175"
_PROVISIONAL_PREF = "leave orders at the loading dock"


class _MergeSpyStore:
    """A store whose merge/read must never run (disabled-backend guard)."""

    def merge_provisional_memory(self, *a, **k):  # pragma: no cover - must not run
        raise AssertionError("merge_provisional_memory must not be called")

    def load_customer_memory(self, *a, **k):  # pragma: no cover - must not run
        raise AssertionError("load_customer_memory must not be called")


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


def _run_turn(monkeypatch, *, store, context, inbound_body="Hi again"):
    """Run ``run_turn`` with ``run_agent_turn`` stubbed; return the injected message."""
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


def _verified_context() -> SimpleNamespace:
    return SimpleNamespace(
        conversation_id="conv-merge-verified",
        sms_session_id=None,
        from_phone=_PHONE,  # same caller who stated the provisional preference
        session_identity_snapshot=SessionIdentitySnapshot(
            outcome="verified_customer",
            resolved_at="2026-07-13T00:00:00Z",
            shopify_customer_id=_SHOPIFY_ID,
            display_name="Merge Co",
        ),
    )


def _audit_count(cur, provisional_key) -> int:
    cur.execute(
        "SELECT count(*) FROM customer_memory_merge_audit WHERE provisional_key = %s",
        (provisional_key,),
    )
    return cur.fetchone()[0]


def test_verified_turn_merges_provisional_and_injects_it_same_turn(datastore, monkeypatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    driver, conn, _ = datastore
    prov_key = _write_provisional(
        driver, phone=_PHONE, key="delivery_habit_note", value=_PROVISIONAL_PREF
    )
    assert prov_key == f"provisional:sms:{normalize_e164(_PHONE)}"

    user_message = _run_turn(
        monkeypatch, store=PostgresGatewayStore(connection=conn), context=_verified_context()
    )

    with conn.cursor() as cur:
        # provisional copies removed, migrated onto the verified id
        cur.execute("SELECT count(*) FROM customer_memory_slot WHERE binding_key = %s", (prov_key,))
        assert cur.fetchone()[0] == 0
        cur.execute(
            "SELECT slot_value, source FROM customer_memory_slot "
            "WHERE binding_key = %s AND slot_name = 'delivery_habit_note'",
            (_SHOPIFY_ID,),
        )
        assert cur.fetchone() == (_PROVISIONAL_PREF, "merged_provisional")
        assert _audit_count(cur, prov_key) == 1

    # merge ran before the read -> the just-merged preference is injected THIS turn
    assert "Customer Memory (preferences):" in user_message
    assert _PROVISIONAL_PREF in user_message


def test_ambiguous_turn_does_not_merge(datastore, monkeypatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    driver, conn, _ = datastore
    prov_key = _write_provisional(
        driver, phone=_PHONE, key="delivery_habit_note", value=_PROVISIONAL_PREF
    )

    context = SimpleNamespace(
        conversation_id="conv-merge-ambiguous",
        sms_session_id=None,
        from_phone=_PHONE,
        session_identity_snapshot=SessionIdentitySnapshot(
            outcome="ambiguous_phone_match",
            resolved_at="2026-07-13T00:00:00Z",
            shopify_customer_ids=["gid://shopify/Customer/1", "gid://shopify/Customer/2"],
        ),
    )

    _run_turn(monkeypatch, store=PostgresGatewayStore(connection=conn), context=context)

    with conn.cursor() as cur:
        # provisional slot untouched, no merge audit row
        cur.execute("SELECT count(*) FROM customer_memory_slot WHERE binding_key = %s", (prov_key,))
        assert cur.fetchone()[0] == 1
        assert _audit_count(cur, prov_key) == 0


def test_unmatched_turn_does_not_merge(datastore, monkeypatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    driver, conn, _ = datastore
    prov_key = _write_provisional(
        driver, phone=_PHONE, key="delivery_habit_note", value=_PROVISIONAL_PREF
    )

    context = SimpleNamespace(
        conversation_id="conv-merge-unmatched",
        sms_session_id=None,
        from_phone=_PHONE,
        session_identity_snapshot=None,  # unmatched caller: still provisional, no merge
    )

    _run_turn(monkeypatch, store=PostgresGatewayStore(connection=conn), context=context)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM customer_memory_slot WHERE binding_key = %s", (prov_key,))
        assert cur.fetchone()[0] == 1
        assert _audit_count(cur, prov_key) == 0


def test_disabled_backend_never_touches_the_store(monkeypatch) -> None:
    # S05/FR-7: TOOL_BACKEND unset -> memory_enabled() False -> neither merge nor read
    # is attempted (the spy store raises if touched); the turn still completes.
    monkeypatch.delenv("TOOL_BACKEND", raising=False)
    user_message = _run_turn(
        monkeypatch, store=_MergeSpyStore(), context=_verified_context()
    )
    assert "Customer Memory" not in user_message
