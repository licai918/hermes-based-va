"""Native entry-point discovery: Hermes loads the toee plugin on its own.

Once ``toee_hermes`` is installed as a ``hermes_agent.plugins`` entry-point package
(ADR-0139), Hermes' own ``discover_plugins()`` finds it via ``importlib.metadata``,
and a per-profile HERMES_HOME (``config.yaml`` enabling ``toee`` + the
``TOEE_HERMES_PROFILE`` selector) drives ``register(ctx)`` for that profile — no
manual ``boot_profile`` call and no ``pythonpath`` injection. This is the
production gateway-embedding discovery path.
"""

from __future__ import annotations

import tempfile

from hermes_cli.plugins import discover_plugins, get_plugin_manager, has_hook
from tools.registry import registry

from hermes_runtime.home import write_profile_home


def test_discover_plugins_loads_external_profile_via_entry_point(monkeypatch) -> None:
    home = write_profile_home(
        profile="customer_service_external",
        home=tempfile.mkdtemp(prefix="hermes-home-"),
    )
    for key, value in home.env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("HERMES_ENABLE_PROJECT_PLUGINS", raising=False)

    discover_plugins(force=True)

    loaded = get_plugin_manager()._plugins.get("toee-tire")
    assert loaded is not None, "toee-tire entry-point plugin was not discovered"
    assert loaded.enabled and not loaded.error

    # The External profile's allowlisted governed tool is registered globally,
    # and the identity/memory injection hook (ADR-0140) is wired.
    assert registry.get_entry("toee_textline_reply__send_message") is not None
    assert has_hook("pre_llm_call")
