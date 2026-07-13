"""S04: hermes-runtime injects the datastore driver for ``toee_customer_memory``.

The live external turn boots the profile with a per-tool ``extra_drivers`` overlay
so ``toee_customer_memory`` routes to the Postgres datastore while every other tool
keeps its mock/composio driver. Injection is conditional on the datastore backend
being configured (``resolve_tool_backend() == "datastore"``); a mock deployment
passes no overlay and the tool stays on mock (full no-DB degradation is S05).

``psycopg``/``PostgresDriver`` live only in hermes-runtime — the plugin overlay
only ever sees an object satisfying the ``ToolDriver`` protocol.

These tests stay hermetic: the seam tests stub ``boot_profile``/``register_turn``
so nothing registers into the shared upstream tool registry, and the persistence
test drives the governed dispatch directly. The ``datastore``-fixtured test reuses
the throwaway-schema harness (conftest) and **skips** when no Postgres is reachable.
"""

from __future__ import annotations

from types import SimpleNamespace

from toee_hermes.execute import execute_tool
from toee_hermes.plugin import _build_driver_selector
from toee_hermes.plugin.profiles import EXTERNAL
from toee_hermes.tool_gate import ToolExecutionContext

from hermes_runtime.boot import boot_profile
from hermes_runtime.openrouter import (
    OPENROUTER_PRIMARY_MODEL,
    OpenRouterConfig,
    make_openrouter_run_turn,
)

VERIFIED = {
    "outcome": "verified_customer",
    "shopify_customer_id": "gid://shopify/Customer/1001",
}

_CONFIG = OpenRouterConfig(
    base_url="https://openrouter.ai/api/v1",
    api_key="sk-or-test",
    model=OPENROUTER_PRIMARY_MODEL,
)


def _capture_extra_drivers(monkeypatch) -> dict:
    """Run one turn with boot + agent-loop stubbed; return the boot_profile kwargs.

    Stubbing keeps this hermetic — no profile registers into the shared upstream
    ``tools.registry`` — so it observes exactly what openrouter hands boot_profile.
    """
    import hermes_runtime.openrouter as openrouter_mod

    captured: dict[str, object] = {}

    def fake_boot(profile: str, **kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(profile=profile, tool_names=[], manager=None)

    monkeypatch.setattr(openrouter_mod, "boot_profile", fake_boot)
    monkeypatch.setattr(
        openrouter_mod,
        "run_agent_turn",
        lambda **_kwargs: {"final_response": "", "messages": []},
    )
    run_turn = make_openrouter_run_turn(
        config=_CONFIG, openai_factory=lambda *_a, **_k: None
    )
    context = SimpleNamespace(
        conversation_id="conv-778",
        sms_session_id=None,
        from_phone="4165550101",
        session_identity_snapshot=None,
    )
    run_turn(context, "Where is my order?")
    return captured


def test_run_turn_injects_the_datastore_driver_when_backend_is_datastore(monkeypatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")

    captured = _capture_extra_drivers(monkeypatch)

    extra = captured.get("extra_drivers")
    assert extra is not None
    # The plugin overlay only sees a ToolDriver; its kind attributes audit rows.
    assert extra["toee_customer_memory"].kind == "datastore"


def test_run_turn_passes_no_overlay_on_a_mock_deployment(monkeypatch) -> None:
    # Scope boundary with S05: unset backend -> no overlay -> tool stays on mock,
    # so a mock deployment never hard-depends on Postgres.
    monkeypatch.delenv("TOOL_BACKEND", raising=False)

    captured = _capture_extra_drivers(monkeypatch)

    assert captured.get("extra_drivers") is None


def test_boot_profile_forwards_extra_drivers_to_register_turn(monkeypatch) -> None:
    # boot_profile threads the overlay into the bound-turn registration path; the
    # spy replaces register_turn so nothing registers into the shared registry.
    import toee_hermes.plugin as plugin_mod

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        plugin_mod, "register_turn", lambda _ctx, **kwargs: captured.update(kwargs)
    )
    sentinel = {"toee_customer_memory": object()}

    boot_profile(EXTERNAL, conversation_id="conv-x", extra_drivers=sentinel)

    assert captured.get("extra_drivers") is sentinel


def test_overlay_dispatch_persists_to_postgres_and_attributes_datastore(datastore) -> None:
    # The brief's integration acceptance: the overlay routes toee_customer_memory to
    # the datastore driver, the governed dispatch persists to customer_memory_slot
    # (throwaway schema — the mock never writes there), and the audit attributes
    # driver.kind = "datastore" (anti-mock).
    driver, conn, _ = datastore
    select = _build_driver_selector(None, {"toee_customer_memory": driver})
    assert select("toee_shopify_read").kind == "mock"  # others unaffected

    result = execute_tool(
        tool="toee_customer_memory",
        action="upsert_preference",
        params={
            "key": "contact_time_preference",
            "value": "mornings",
            "source": "customer_explicit",
        },
        context=ToolExecutionContext(profile=EXTERNAL, identity=VERIFIED),
        driver=select("toee_customer_memory"),
    )

    assert result.ok
    assert result.audit.driver == "datastore"
    with conn.cursor() as cur:
        cur.execute(
            "SELECT slot_value FROM customer_memory_slot "
            "WHERE binding_key = %s AND slot_name = %s",
            ("gid://shopify/Customer/1001", "contact_time_preference"),
        )
        assert cur.fetchone() == ("mornings",)
