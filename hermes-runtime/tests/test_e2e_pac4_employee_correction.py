"""S19 — PAC-4 end-to-end proof: an employee's Workbench correction takes effect on
the customer's very next turn.

Chains the two halves the milestone built and tested SEPARATELY:
  - S16 (employee WRITE): a Workbench correction dispatched over the real HTTP
    ``/v1/tools:dispatch`` route under ``internal_copilot`` resolves the case's
    identity and binds to the customer's own read key.
  - S07 (customer READ): the customer's next external turn injects whatever is
    stored under that same key.

Each half already has its own passing round-trip test (S16:
``test_dispatch_customer_memory_correction_binds_to_verified_customers_read_key`` in
test_tool_dispatch_app.py; S07: test_openrouter_memory_injection.py). This file
proves the property that only holds when BOTH are wired correctly at once — an
employee correction is genuinely visible to the customer on their next turn — by
driving one employee write and one customer turn through the SAME Postgres row and
asserting the value crosses the seam unmodified (PRD PAC-4). If the dispatch route
ever binds to the wrong key again (S16's bug) or the read ever derives a different
key, the corrected/cleared value silently fails to (dis)appear and these tests catch
it — never a hand-inserted row standing in for the employee write.

Real Postgres via the shared ``datastore`` fixture (skip-if-no-DB, ADR-0142).
"""

from __future__ import annotations

from types import SimpleNamespace

from starlette.testclient import TestClient

from toee_hermes.gateway.ingress import SessionIdentitySnapshot

import hermes_runtime.openrouter as openrouter_mod
from hermes_runtime.live import _scripted_openai_factory
from hermes_runtime.openrouter import (
    OPENROUTER_PRIMARY_MODEL,
    OpenRouterConfig,
    make_openrouter_run_turn,
)
from hermes_runtime.postgres_gateway_store import PostgresGatewayStore
from hermes_runtime.tool_dispatch_app import create_tool_dispatch_app

API_TOKEN = "test-copilot-api-token"

_CONFIG = OpenRouterConfig(
    base_url="https://openrouter.ai/api/v1",
    api_key="sk-or-test",
    model=OPENROUTER_PRIMARY_MODEL,
)

_SHOPIFY_ID = "gid://shopify/Customer/pac4001"
_SLOT = "contact_time_preference"


def _seed_verified_case(conn, *, case_id, thread_id, shopify_customer_id, channel_identity):
    """Seed a customer_thread + case bound to a VERIFIED Shopify customer.

    Mirrors ``_seed_verified_case`` in test_tool_dispatch_app.py (the S16 precedent
    for the same case->thread identity lookup the dispatch route resolves through).
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO customer_thread (id, channel, channel_identity, shopify_customer_id)"
            " VALUES (%s, 'sms', %s, %s)",
            (thread_id, channel_identity, shopify_customer_id),
        )
        cur.execute(
            "INSERT INTO cases (id, channel, customer_thread_id) VALUES (%s, 'sms', %s)",
            (case_id, thread_id),
        )
    conn.commit()


def _employee_dispatch(driver, store, *, action: str, case_id: str, key: str, value: str | None = None):
    """POST an employee correction/clear over the real HTTP dispatch route (S16)."""
    app = create_tool_dispatch_app(
        api_token=API_TOKEN, profile="internal_copilot", driver=driver, store=store
    )
    params: dict[str, object] = {"case_id": case_id, "key": key}
    if value is not None:
        params["value"] = value
    return TestClient(app).post(
        "/v1/tools:dispatch",
        headers={"Authorization": f"Bearer {API_TOKEN}"},
        json={
            "tool": "toee_customer_memory",
            "action": action,
            "params": params,
            "actor_account_id": "acct_rep_pac4",
        },
    )


def _customers_next_turn(
    monkeypatch, *, store, shopify_customer_id: str, from_phone: str, conversation_id: str
) -> str:
    """Run the CUSTOMER's next external turn (S07 read path); return the injected
    user message. ``run_agent_turn`` is stubbed -- no model/network is used -- so the
    read + shared binding derivation + render run for real and the assertion is on
    the exact prompt handed to the model."""
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
        conversation_id=conversation_id,
        sms_session_id=None,
        from_phone=from_phone,
        session_identity_snapshot=SessionIdentitySnapshot(
            outcome="verified_customer",
            resolved_at="2026-07-14T00:00:00Z",
            shopify_customer_id=shopify_customer_id,
        ),
    )
    run_turn(context, "Hi again")
    return captured["user_message"]


def test_employee_correction_takes_effect_on_customers_next_turn(datastore, monkeypatch) -> None:
    """PAC-4 core loop: an employee correction dispatched via the real Workbench
    path (S16) persists under the customer's bare shopify_customer_id, and the
    customer's own NEXT external turn (S07) injects the corrected value -- not a
    stale one, not nothing."""
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    driver, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    corrected_value = "mornings only, no texts after 6pm"

    _seed_verified_case(
        conn,
        case_id="case-pac4-correct",
        thread_id="thr-pac4-correct",
        shopify_customer_id=_SHOPIFY_ID,
        channel_identity="+14165550188",
    )

    # 1. Employee correction, over the real HTTP dispatch route (S16).
    response = _employee_dispatch(
        driver, store,
        action="upsert_preference", case_id="case-pac4-correct",
        key=_SLOT, value=corrected_value,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    # Bound to the customer's OWN key, not the dead provisional:{channel_identity_id}
    # fallback (S16's bug) -- the response already shows it...
    assert body["data"]["binding_key"] == _SHOPIFY_ID
    assert body["data"]["source"] == "employee_confirmed"

    # ...but read Postgres directly too: the row genuinely persisted under the bare
    # shopify id, not merely echoed back in the HTTP response.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT slot_value FROM customer_memory_slot"
            " WHERE binding_key = %s AND slot_name = %s",
            (_SHOPIFY_ID, _SLOT),
        )
        assert cur.fetchone() == (corrected_value,)

    # 2. The customer's own NEXT turn, a different phone (verified binds on the
    #    Shopify id, never the channel -- same discriminator S07's own test uses).
    injected = _customers_next_turn(
        monkeypatch, store=store, shopify_customer_id=_SHOPIFY_ID,
        from_phone="+14165559981", conversation_id="conv-pac4-correct",
    )
    assert "Customer Memory (preferences):" in injected
    assert corrected_value in injected


def test_employee_clear_removes_slot_from_customers_next_turn(datastore, monkeypatch) -> None:
    """PAC-4 clear path: an employee clear_preference (S16) removes the slot such
    that the customer's next turn no longer injects it -- proven as a genuine
    before/after transition, not a tautological 'never had anything'."""
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    driver, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    original_value = "text only, never call"

    _seed_verified_case(
        conn,
        case_id="case-pac4-clear",
        thread_id="thr-pac4-clear",
        shopify_customer_id=_SHOPIFY_ID,
        channel_identity="+14165550177",
    )
    seeded = _employee_dispatch(
        driver, store,
        action="upsert_preference", case_id="case-pac4-clear",
        key=_SLOT, value=original_value,
    )
    assert seeded.json()["ok"] is True

    before = _customers_next_turn(
        monkeypatch, store=store, shopify_customer_id=_SHOPIFY_ID,
        from_phone="+14165559982", conversation_id="conv-pac4-clear-before",
    )
    assert original_value in before  # genuine transition, not vacuously true below

    # Employee clears it, over the same real dispatch route.
    cleared = _employee_dispatch(
        driver, store, action="clear_preference", case_id="case-pac4-clear", key=_SLOT,
    )
    assert cleared.status_code == 200
    cleared_body = cleared.json()
    assert cleared_body["ok"] is True
    assert cleared_body["data"]["binding_key"] == _SHOPIFY_ID

    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM customer_memory_slot"
            " WHERE binding_key = %s AND slot_name = %s",
            (_SHOPIFY_ID, _SLOT),
        )
        assert cur.fetchone()[0] == 0

    after = _customers_next_turn(
        monkeypatch, store=store, shopify_customer_id=_SHOPIFY_ID,
        from_phone="+14165559983", conversation_id="conv-pac4-clear-after",
    )
    assert "Customer Memory" not in after  # the whole block disappears, not just the value
