"""Boot a Hermes profile with the toee_hermes plugin registered (ADR-0139).

``boot_profile`` constructs a real upstream ``PluginContext``, runs the plugin's
``register(ctx)`` for the requested profile, and returns the registered tool names
plus a governed ``dispatch`` into the shared tool registry. This is the in-process
embedding the external channel pipeline uses (`from run_agent import AIAgent`); the
SDK is imported here and nowhere in the dependency-free eval runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


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


def _boot(profile: str, register_fn: Any) -> BootedProfile:
    """Construct a real PluginContext, run ``register_fn(ctx)``, return the booted profile.

    ``toee_hermes`` must be importable. The test harness puts ``../hermes`` on the
    path (``pythonpath`` in pyproject); the gateway-embedding slice replaces this
    with the installable ``hermes_agent.plugins`` entry-point package (ADR-0139),
    at which point Hermes' own loader discovers the plugin without this call.
    """
    from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest

    manager = PluginManager()
    manifest = PluginManifest(name="toee-tire")
    ctx = PluginContext(manifest, manager)
    # resolve_profile(ctx) reads ctx.profile first (ADR-0034 default-deny by profile).
    ctx.profile = profile
    register_fn(ctx)
    return BootedProfile(
        profile=profile,
        tool_names=sorted(manager._plugin_tool_names),
        manager=manager,
    )


def boot_profile(
    profile: str,
    *,
    conversation_id: Optional[str] = None,
    sms_session_id: Optional[str] = None,
) -> BootedProfile:
    """Register the profile's allowlisted toee_* tools into a real PluginContext.

    When ``conversation_id`` is given, the profile is booted for one async Textline
    turn via :func:`toee_hermes.plugin.register_turn`: every governed dispatch
    carries that turn binding and the turn-binding gate constrains
    ``toee_textline_reply.send_message`` to the bound conversation (ADR-0107/0066).
    Without it, the unbound :func:`register` path is used (eval/replay + Copilot).
    """
    from toee_hermes.plugin import register, register_turn

    if conversation_id is not None:
        return _boot(
            profile,
            lambda ctx: register_turn(
                ctx, conversation_id=conversation_id, sms_session_id=sms_session_id
            ),
        )
    return _boot(profile, register)


def boot_profile_eval(
    profile: str,
    *,
    driver: Any,
    gate: Any,
    identity: Optional[Any] = None,
) -> BootedProfile:
    """Boot a profile for a Launch Eval recording turn (ADR-0071, ADR-0139).

    Injects the scenario's MockDriver (``driver``), the External-profile Tool Gate
    (``gate``), and the closed-over Session Identity Snapshot (``identity``, ADR-0043)
    via :func:`toee_hermes.plugin.register_eval`, so a recorded live ``AIAgent`` turn
    dispatches through the scenario's mock data and policy — not the default mock.
    """
    from toee_hermes.plugin import register_eval

    return _boot(
        profile,
        lambda ctx: register_eval(ctx, driver=driver, gate=gate, identity=identity),
    )
