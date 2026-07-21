"""S04: hermes-runtime injects the datastore driver for ``toee_customer_memory``.

The live external turn boots the profile with a per-tool ``extra_drivers`` overlay
so ``toee_customer_memory`` routes to the Postgres datastore while every other tool
keeps its mock/composio driver. Injection is gated by
:func:`hermes_runtime.tool_backend.memory_enabled` (S05's single source of truth,
shared with the S07/S08 read gates); a mock/unset deployment passes no overlay and
the tool stays on mock — the turn still completes with no hard Postgres dependency.

``psycopg``/``PostgresDriver`` live only in hermes-runtime — the plugin overlay
only ever sees an object satisfying the ``ToolDriver`` protocol.

These tests stay hermetic: the seam tests stub ``boot_profile``/``register_turn``
so nothing registers into the shared upstream tool registry, and the persistence
test drives the governed dispatch directly. The ``datastore``-fixtured test reuses
the throwaway-schema harness (conftest) and **skips** when no Postgres is reachable.
"""

from __future__ import annotations

import json
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


def test_run_turn_passes_no_overlay_when_backend_is_unset(monkeypatch) -> None:
    # S05/FR-7: unset backend -> memory_enabled() is False -> no overlay -> tool
    # stays on mock, so a mock deployment never hard-depends on Postgres and the
    # turn still completes (no exception raised).
    monkeypatch.delenv("TOOL_BACKEND", raising=False)

    captured = _capture_extra_drivers(monkeypatch)

    assert captured.get("extra_drivers") is None


def test_run_turn_passes_no_overlay_when_backend_is_explicitly_mock(monkeypatch) -> None:
    # Same S05 contract, spelled out for TOOL_BACKEND=mock (not just unset) per the
    # brief's literal "unset / mock" wording.
    monkeypatch.setenv("TOOL_BACKEND", "mock")

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


def test_boot_profile_forwards_extra_drivers_to_register(monkeypatch) -> None:
    # S20/PAC-4 gap #2: the UNBOUND boot path (no conversation_id -- Copilot draft
    # turn) also forwards the overlay; mirrors the bound-path test above.
    import toee_hermes.plugin as plugin_mod

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        plugin_mod, "register", lambda _ctx, **kwargs: captured.update(kwargs)
    )
    sentinel = {"toee_customer_memory": object()}

    boot_profile(EXTERNAL, extra_drivers=sentinel)

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


class _SentinelDriver:
    """A distinguishable driver: any dispatch through it proves it, not mock, ran."""

    kind = "sentinel"

    def execute(self, request, context):  # noqa: ANN001 - matches ToolDriver protocol
        return {"sentinel": True}


def test_boot_profile_survives_a_later_lazy_sdk_plugin_discovery(monkeypatch, tmp_path) -> None:
    """Regression: a live-verified race, root-caused via a real gateway run.

    Hermes' own entry-point plugin loader ALSO knows about ``toee-tire`` (the
    "gateway-embedding slice" ``boot.py`` docstrings anticipated, and
    ``test_entrypoint_discovery.py`` proves works standalone): the first time
    anything in the process imports Hermes' ``model_tools`` -- lazily, e.g. inside
    ``AIAgent`` setup, entirely outside our control -- it runs
    ``hermes_cli.plugins.discover_plugins()``, which calls our plugin's BARE,
    unbound ``register(ctx)`` (no ``extra_drivers``). The shared upstream
    ``tools.registry`` is last-write-wins per tool name, so if that lazy trigger
    lands AFTER an overlay boot (``openrouter.py``'s ``extra_drivers=
    _turn_extra_drivers()``), it silently clobbers every handler back onto mock.
    A live gateway run (3 inbound SMS webhooks against a real KNOWLEDGE_BACKEND=
    retriever + OpenRouter turn) caught this directly: the overlay boot registered
    a real ``KnowledgeDriver``, and ~2s later the SDK's lazy ``discover_plugins()``
    reset ``toee_knowledge_search`` to mock mid-turn (stack trace confirmed the
    ``model_tools.py`` -> ``discover_plugins`` -> bare ``register`` chain).

    This reproduces it deterministically: a per-profile HERMES_HOME (same
    ``write_profile_home`` seam ``test_entrypoint_discovery.py`` uses) makes the
    SDK's manifest scan actually find ``toee-tire``; the plugin manager is forced
    back to "not yet discovered" (simulating a fresh process); then this boots
    with a sentinel overlay and fires the SAME lazy trigger the real ``AIAgent``
    setup would -- dispatch must still reach the sentinel, not mock.
    """
    from hermes_cli.plugins import discover_plugins, get_plugin_manager
    from tools.registry import registry

    from hermes_runtime.home import write_profile_home

    home = write_profile_home(profile=EXTERNAL, home=tmp_path / "hermes-home")
    for key, value in home.env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("HERMES_ENABLE_PROJECT_PLUGINS", raising=False)
    get_plugin_manager()._discovered = False  # simulate a fresh, undiscovered process

    sentinel = _SentinelDriver()
    boot_profile(EXTERNAL, extra_drivers={"toee_knowledge_search": sentinel})

    # The SAME lazy trigger AIAgent's own setup fires on first use of model_tools;
    # idempotent by default (a no-op once already discovered), so this must not
    # be able to clobber our boot's registration.
    discover_plugins()

    result = registry.dispatch(
        "toee_knowledge_search__search_public_site", {"query": "warranty policy"}
    )
    assert json.loads(result) == {"sentinel": True}
