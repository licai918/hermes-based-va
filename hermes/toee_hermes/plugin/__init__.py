"""Toee Tire Hermes plugin registration (ADR-0139).

``register(ctx)`` is the Hermes plugin entry point. It resolves the active profile
(ADR-0034/35/38), registers every allowlisted ``(tool, action)`` as a Hermes tool
backed by governed dispatch, and registers the ``pre_llm_call`` identity/memory
injection hook (ADR-0140). Default-deny is enforced by *not registering* tools
outside the profile's allowlist. Only this layer (and the gateway embedding) may
import Hermes; ``apps/workbench`` calls the per-profile API Server over HTTP.
"""

from __future__ import annotations

from typing import Any

from typing import Callable, Optional

from ..drivers.base import resolve_integration_driver
from ..drivers.composio import COMPOSIO_LAYER1_TOOLS, build_composio_driver
from ..drivers.mock import MockDriver, create_all_mock_handlers
from ..execute import ToolDriver
from ..gates import create_turn_binding_gate
from ..tool_gate import ToolExecutionContext, ToolGate
from .hooks import make_pre_llm_call_hook
from .profiles import allowlisted_tools, resolve_profile
from .schemas import build_tool_schemas
from .tools import ContextProvider, make_tool_handler

# Builds the per-call context provider once the active profile is resolved. The
# binding (if any) is closed over here rather than read from per-call kwargs,
# because the agent — not the embedding — invokes the governed handler.
ProviderFactory = Callable[[str], ContextProvider]

# Picks the driver for one tool. Per-tool selection keeps the audit record's
# driver.kind accurate when Composio backs only the Layer 1 tools (ADR-0128).
DriverSelector = Callable[[str], ToolDriver]


def _build_driver_selector(injected: Optional[ToolDriver]) -> DriverSelector:
    """Resolve a per-tool driver selector (mock-first, ADR-0137).

    An ``injected`` driver (the eval recording path, :func:`register_eval`)
    overrides ALL tools and short-circuits backend resolution, so eval/replay never
    builds a live driver. Otherwise ``INTEGRATION_DRIVER`` selects the backend:
    ``mock`` (default) serves every tool, while ``composio`` routes only the three
    Layer 1 tools to the Composio driver and leaves the rest on mock (ADR-0128).
    """
    if injected is not None:
        return lambda _tool: injected

    kind = resolve_integration_driver()
    mock_driver = MockDriver(create_all_mock_handlers())
    if kind == "mock":
        return lambda _tool: mock_driver
    if kind == "composio":
        composio_driver = build_composio_driver()
        return lambda tool: (
            composio_driver if tool in COMPOSIO_LAYER1_TOOLS else mock_driver
        )
    raise NotImplementedError(
        f'Integration driver "{kind}" is not implemented yet (mock-first, ADR-0137).'
    )


def _make_context_provider(
    profile: str,
    *,
    identity: Optional[Any] = None,
    conversation_id: Optional[str] = None,
    sms_session_id: Optional[str] = None,
) -> ContextProvider:
    """Bind the profile (and optional async turn binding) into a context builder.

    Identity-bearing kwargs (``identity``/``user_id``/``connected_account_id``)
    are read when the embedding layer passes them; until then the context carries
    the profile alone and identity-scoped reads see ``identity is None``. A closed
    over ``identity`` (the eval Session Identity Snapshot, ADR-0043) takes
    precedence, because the agent loop never supplies it as a per-call kwarg. The
    async Textline turn binding (``conversation_id``/``sms_session_id``, ADR-0107)
    is injected by :func:`register_turn` and closed over here — never model-supplied.
    """

    def provider(kwargs: dict[str, Any]) -> ToolExecutionContext:
        return ToolExecutionContext(
            profile=profile,
            identity=identity if identity is not None else kwargs.get("identity"),
            user_id=kwargs.get("user_id"),
            connected_account_id=kwargs.get("connected_account_id"),
            conversation_id=conversation_id,
            sms_session_id=sms_session_id,
        )

    return provider


def _register(
    ctx: Any,
    *,
    provider_factory: ProviderFactory,
    driver: Optional[ToolDriver] = None,
    gate: Optional[ToolGate] = None,
) -> None:
    """Register a profile's allowlisted tools + the injection hook.

    The turn-binding gate (ADR-0107/0066) is the default gate; it is inert unless
    the context carries a ``conversation_id`` (eval/replay + Copilot paths are
    unbound), so only :func:`register_turn` activates the binding constraint. The
    Launch Eval recording path (:func:`register_eval`) injects the scenario's
    ``driver`` (its MockDriver) and ``gate`` (the External-profile gate) instead.
    """
    profile = resolve_profile(ctx)
    allow = allowlisted_tools(profile)
    driver_for = _build_driver_selector(driver)
    context_provider = provider_factory(profile)
    active_gate = gate if gate is not None else create_turn_binding_gate()

    for entry in build_tool_schemas():
        if entry["toolset"] not in allow:
            continue
        handler = make_tool_handler(
            tool=entry["tool"],
            action=entry["action"],
            driver=driver_for(entry["tool"]),
            context_provider=context_provider,
            gate=active_gate,
        )
        ctx.register_tool(
            name=entry["schema"]["name"],
            toolset=entry["toolset"],
            schema=entry["schema"],
            handler=handler,
        )

    ctx.register_hook("pre_llm_call", make_pre_llm_call_hook())


def register(ctx: Any) -> None:
    """Register allowlisted Domain Adapter Tools + the injection hook for a profile.

    This is the Hermes plugin entry point (eval/replay + Copilot paths): the
    context carries no async turn binding, so the reply tool is unconstrained.
    """
    _register(ctx, provider_factory=lambda profile: _make_context_provider(profile))


def register_turn(
    ctx: Any, *, conversation_id: str, sms_session_id: Optional[str] = None
) -> None:
    """Register for one async Textline turn bound to ``conversation_id`` (ADR-0107).

    The gateway embedding calls this after the internal job reloads + verifies the
    inbound binding; every governed dispatch then carries the binding, and the
    turn-binding gate rejects a ``toee_textline_reply.send_message`` aimed at any
    other conversation (ADR-0066).
    """
    _register(
        ctx,
        provider_factory=lambda profile: _make_context_provider(
            profile,
            conversation_id=conversation_id,
            sms_session_id=sms_session_id,
        ),
    )


def register_eval(
    ctx: Any,
    *,
    driver: ToolDriver,
    gate: ToolGate,
    identity: Optional[Any] = None,
) -> None:
    """Register for a Launch Eval recording turn (ADR-0071, ADR-0139).

    Injects the scenario's ``driver`` (its MockDriver), the External-profile
    ``gate``, and the closed-over Session Identity Snapshot (ADR-0043), so a
    recorded live ``AIAgent`` turn dispatches through the scenario's mock data and
    policy. This path is unbound (no async Textline ``conversation_id``), so the
    reply tool is unconstrained — recording captures whatever conversation the
    scenario's scripted/model turn targets.
    """
    _register(
        ctx,
        provider_factory=lambda profile: _make_context_provider(
            profile, identity=identity
        ),
        driver=driver,
        gate=gate,
    )


__all__ = ["register", "register_turn", "register_eval"]
