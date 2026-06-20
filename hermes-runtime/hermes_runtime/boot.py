"""Boot a Hermes profile with the toee_hermes plugin registered (ADR-0139).

``boot_profile`` constructs a real upstream ``PluginContext``, runs the plugin's
``register(ctx)`` for the requested profile, and returns the registered tool names
plus a governed ``dispatch`` into the shared tool registry. This is the in-process
embedding the external channel pipeline uses (`from run_agent import AIAgent`); the
SDK is imported here and nowhere in the dependency-free eval runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class BootedProfile:
    """A loaded Hermes profile: its registered toee tools and a governed dispatch."""

    profile: str
    tool_names: list[str]
    manager: Any

    def dispatch(self, name: str, args: dict, **kwargs: Any) -> str:
        """Dispatch a registered tool through the shared registry (returns JSON)."""
        from tools.registry import registry

        return registry.dispatch(name, args, **kwargs)


def boot_profile(profile: str) -> BootedProfile:
    """Register the profile's allowlisted toee_* tools into a real PluginContext.

    ``toee_hermes`` must be importable. The test harness puts ``../hermes`` on the
    path (``pythonpath`` in pyproject); the gateway-embedding slice replaces this
    with the installable ``hermes_agent.plugins`` entry-point package (ADR-0139),
    at which point Hermes' own loader discovers the plugin without this call.
    """
    from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest

    from toee_hermes.plugin import register

    manager = PluginManager()
    manifest = PluginManifest(name="toee-tire")
    ctx = PluginContext(manifest, manager)
    # resolve_profile(ctx) reads ctx.profile first (ADR-0034 default-deny by profile).
    ctx.profile = profile
    register(ctx)
    return BootedProfile(
        profile=profile,
        tool_names=sorted(manager._plugin_tool_names),
        manager=manager,
    )
