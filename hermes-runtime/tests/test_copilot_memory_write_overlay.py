"""S20 (PAC-4 gap #2): Copilot AI-draft-turn writes reach the datastore, not mock.

S08 already threads the case's identity into the Copilot draft turn's (unbound)
``ToolExecutionContext``, so an employee-confirmed correction binds to the SAME key
the customer's own turn reads. What was still missing: the UNBOUND boot path
(``register()``, no ``conversation_id``) never carried the ``extra_drivers``
overlay S04 gave the BOUND external turn (``register_turn``), so an agent-initiated
``toee_customer_memory.upsert_preference`` during a copilot draft always fell to the
ephemeral MockDriver and was silently discarded.

This mirrors ``test_composite_driver_overlay.py`` (the overlay/injection shape) and
``test_copilot_memory_injection.py`` (the copilot seam + real-Postgres fixture
conventions). The hermetic tests stub ``boot_profile`` so nothing registers into the
shared upstream ``tools.registry``; the integration test drives a REAL scripted
``AIAgent`` turn through the real governed dispatch path, substituting only the
datastore driver's CONNECTION (via ``select_tool_driver``) so its write lands in the
test's throwaway schema instead of a fresh connection to the default schema.
"""

from __future__ import annotations

from types import SimpleNamespace

from hermes_runtime.copilot_turn import make_copilot_run_turn
from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

_VERIFIED_SHOPIFY_ID = "gid://shopify/Customer/50501"


class _NullStore:
    """A store with no case/memory -- keeps the hermetic tests DB-independent.

    The hermetic tests below only care about what ``make_copilot_run_turn`` hands
    ``boot_profile``; the case/memory READ side (S08, already covered by
    ``test_copilot_memory_injection.py``) is irrelevant here, so this avoids a real
    Postgres round trip for tests that stub ``boot_profile`` anyway.
    """

    def load_case_identity(self, case_id):
        return None

    def load_customer_memory(self, binding_key):
        return []


def _capture_copilot_boot_kwargs(monkeypatch, *, store=None) -> dict:
    """Run one copilot draft turn with boot + agent-loop stubbed; return boot_profile kwargs.

    Stubbing keeps this hermetic -- no profile registers into the shared upstream
    ``tools.registry`` -- so it observes exactly what ``make_copilot_run_turn`` hands
    ``boot_profile`` (mirrors ``_capture_extra_drivers`` in
    ``test_composite_driver_overlay.py``, one seam further in).
    """
    import hermes_runtime.copilot_turn as copilot_mod

    captured: dict[str, object] = {}

    def fake_boot(profile: str, **kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(profile=profile, tool_names=[], manager=None)

    monkeypatch.setattr(copilot_mod, "boot_profile", fake_boot)
    run_turn = make_copilot_run_turn(
        scripted_completions=[{"content": "ok"}],
        store=store if store is not None else _NullStore(),
    )
    run_turn(channel="sms", case_id="case-x")
    return captured


def test_copilot_run_turn_injects_the_datastore_driver_when_backend_is_datastore(monkeypatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")

    captured = _capture_copilot_boot_kwargs(monkeypatch)

    extra = captured.get("extra_drivers")
    assert extra is not None
    # The plugin overlay only sees a ToolDriver; its kind attributes audit rows.
    assert extra["toee_customer_memory"].kind == "datastore"


def test_copilot_run_turn_merges_the_knowledge_overlay_alongside_memory(monkeypatch) -> None:
    # S10 (FR-5): boot_profile receives the SAME merged dict _turn_extra_drivers()
    # builds on the copilot draft turn -- both overlays land when both backends
    # are on, mirroring the external turn (test_openrouter.py's sibling test).
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.setenv("KNOWLEDGE_BACKEND", "retriever")

    captured = _capture_copilot_boot_kwargs(monkeypatch)

    extra = captured.get("extra_drivers")
    assert extra is not None
    assert set(extra.keys()) == {"toee_customer_memory", "toee_knowledge_search"}
    assert extra["toee_customer_memory"].kind == "datastore"
    assert extra["toee_knowledge_search"].kind == "knowledge"


def test_copilot_run_turn_passes_no_overlay_when_backend_is_unset(monkeypatch) -> None:
    # S05/FR-7 parity: unset backend -> memory_enabled() False -> no overlay -> the
    # tool stays on mock, and the datastore driver is never even constructed (a mock
    # deployment must never hard-depend on Postgres).
    monkeypatch.delenv("TOOL_BACKEND", raising=False)
    # select_tool_driver now lives behind tool_backend._customer_memory_extra_drivers
    # (Standards fix #1 -- hoisted out of copilot_turn.py so openrouter.py and
    # copilot_turn.py share one definition instead of two copies); patch it there.
    import hermes_runtime.tool_backend as tool_backend_mod

    def _boom(*_a, **_k):
        raise AssertionError("select_tool_driver must not be called when memory is disabled")

    monkeypatch.setattr(tool_backend_mod, "select_tool_driver", _boom)

    captured = _capture_copilot_boot_kwargs(monkeypatch)

    assert captured.get("extra_drivers") is None


def test_copilot_run_turn_passes_no_overlay_when_backend_is_explicitly_mock(monkeypatch) -> None:
    # Same contract, spelled out for TOOL_BACKEND=mock (not just unset).
    monkeypatch.setenv("TOOL_BACKEND", "mock")
    # select_tool_driver now lives behind tool_backend._customer_memory_extra_drivers
    # (Standards fix #1 -- hoisted out of copilot_turn.py so openrouter.py and
    # copilot_turn.py share one definition instead of two copies); patch it there.
    import hermes_runtime.tool_backend as tool_backend_mod

    def _boom(*_a, **_k):
        raise AssertionError("select_tool_driver must not be called when memory is disabled")

    monkeypatch.setattr(tool_backend_mod, "select_tool_driver", _boom)

    captured = _capture_copilot_boot_kwargs(monkeypatch)

    assert captured.get("extra_drivers") is None


def _seed_case(
    conn,
    *,
    case_id,
    thread_id,
    channel_identity,
    shopify_customer_id,
    channel="sms",
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


def test_copilot_draft_turn_scripted_write_persists_to_datastore_under_verified_customer_key(
    datastore, monkeypatch
) -> None:
    # The S20 central proof: a copilot draft turn's SCRIPTED agent calls
    # toee_customer_memory.upsert_preference for a VERIFIED-customer case. With the
    # extra_drivers overlay now threaded through boot_profile -> register() ->
    # _register -> _build_driver_selector, the write reaches Postgres -- under the
    # SAME bare shopify_customer_id key S08 already binds context.identity to --
    # tagged source=copilot_agent (S01: this unbound draft turn never sets
    # context.user_id, so it is honestly labelled, never employee_confirmed),
    # instead of being silently discarded by the ephemeral mock.
    driver, conn, _ = datastore
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    import hermes_runtime.tool_backend as tool_backend_mod

    # select_tool_driver's default PostgresDriver() opens a FRESH connection (its own
    # dsn), which would miss this test's throwaway schema entirely. Substitute the
    # fixture's schema-bound instance -- the ONLY substitution here: boot_profile,
    # register(), _register, _build_driver_selector, and execute_tool all run for
    # real, exactly as they would with a real TOOL_BACKEND=datastore deployment.
    # (select_tool_driver lives behind tool_backend._customer_memory_extra_drivers,
    # Standards fix #1 -- patch it there, not on copilot_turn's old local copy.)
    monkeypatch.setattr(tool_backend_mod, "select_tool_driver", lambda *_a, **_k: driver)

    _seed_case(
        conn,
        case_id="case-mem-write",
        thread_id="thr-mem-write",
        channel_identity="+14165550188",
        shopify_customer_id=_VERIFIED_SHOPIFY_ID,
    )

    run_turn = make_copilot_run_turn(
        scripted_completions=[
            {
                "tool_calls": [
                    {
                        "name": "toee_customer_memory__upsert_preference",
                        "arguments": {
                            "key": "contact_time_preference",
                            "value": "mornings",
                        },
                    }
                ]
            },
            {"content": "Got it, I've noted mornings work best for you."},
        ],
        store=PostgresGatewayStore(connection=conn),
    )

    result = run_turn(channel="sms", case_id="case-mem-write")

    assert result["draft"]  # the turn completed past the tool call
    with conn.cursor() as cur:
        cur.execute(
            "SELECT slot_value, source FROM customer_memory_slot"
            " WHERE binding_key = %s AND slot_name = %s",
            (_VERIFIED_SHOPIFY_ID, "contact_time_preference"),
        )
        row = cur.fetchone()
    assert row == ("mornings", "copilot_agent")  # anti-mock: mock never writes here
