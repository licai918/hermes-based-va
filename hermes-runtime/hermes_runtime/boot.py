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

    That entry-point install means the SDK's OWN plugin loader ALSO knows about
    ``toee-tire`` now: the first time anything in this process imports Hermes'
    ``model_tools`` (module-level, inside ``AIAgent`` setup -- lazy and outside
    our control) it runs ``hermes_cli.plugins.discover_plugins()``, which calls
    our plugin's BARE, unbound ``register(ctx)`` -- no ``extra_drivers``, no
    turn binding. The shared upstream ``tools.registry`` singleton is
    last-write-wins per tool name (``registry.register()``), so if that lazy
    trigger lands AFTER this function's overlay-aware registration (S04/S09/S10:
    ``extra_drivers``), it silently clobbers every handler back onto the default
    mock -- the live race this function used to leave to chance (verified via a
    live gateway run: the SDK's bare ``register()`` landed ~2s after an
    overlay boot and reset ``toee_knowledge_search`` to mock mid-turn).
    Calling ``discover_plugins()`` here FIRST forces that lazy trigger to run (if
    it hasn't already) before our own registration, so our overlay-aware boot is
    always what registers last. It's idempotent past the first call (guarded by
    a ``_discovered`` flag on the SDK's own plugin-manager singleton), so this
    costs nothing on every boot after the first.
    """
    from hermes_cli.plugins import (
        PluginContext,
        PluginManager,
        PluginManifest,
        discover_plugins,
    )

    discover_plugins()  # idempotent; NOT proof against a future discover_and_load(force=True),
    # which clears the registry and re-runs bare register() -- no turn path uses force today

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
    identity: Optional[Any] = None,
    extra_drivers: Optional[dict[str, Any]] = None,
) -> BootedProfile:
    """Register the profile's allowlisted toee_* tools into a real PluginContext.

    When ``conversation_id`` is given, the profile is booted for one async Textline
    turn via :func:`toee_hermes.plugin.register_turn`: every governed dispatch
    carries that turn binding and the turn-binding gate constrains
    ``toee_textline_reply.send_message`` to the bound conversation (ADR-0107/0066).
    Without it, the unbound :func:`register` path is used (eval/replay + Copilot).

    ``extra_drivers`` is the turn's per-tool driver override (S04): the embedding
    passes ``{"toee_customer_memory": PostgresDriver(...)}`` so Customer Memory
    persists to the datastore. The values are ``ToolDriver`` objects; the type is
    ``Any`` here so ``psycopg``/``PostgresDriver`` never reach this module. Both the
    bound (``register_turn``, the live external turn) and unbound (``register``, the
    Copilot draft turn, S20/PAC-4 gap #2) paths carry it — an agent-initiated
    ``toee_customer_memory`` write on the unbound path used to always fall to the
    ephemeral mock even though S08 already binds the right identity.

    ``identity`` on the UNBOUND path (Copilot draft turn, S08) threads the case's
    thread identity into the ToolExecutionContext so an employee-confirmed memory
    correction binds from context; the eval/replay callers pass none, unchanged.
    """
    from toee_hermes.plugin import register, register_turn

    if conversation_id is not None:
        return _boot(
            profile,
            lambda ctx: register_turn(
                ctx,
                conversation_id=conversation_id,
                sms_session_id=sms_session_id,
                identity=identity,
                extra_drivers=extra_drivers,
            ),
        )
    return _boot(
        profile,
        lambda ctx: register(ctx, identity=identity, extra_drivers=extra_drivers),
    )


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
