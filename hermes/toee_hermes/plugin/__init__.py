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

# Catalog actions that must NEVER become an LLM-callable tool, even though their
# toolset is profile-allowlisted for other actions (0.0.3 S05). Registering
# every allowlisted-toolset action is otherwise correct (ADR-0034 default-deny
# is by toolset), but toee_identity_lookup.link_identity is a governed Identity
# Graph WRITE meant only for the deterministic tools:dispatch HTTP surface
# (hermes-runtime/hermes_runtime/tool_dispatch_composition.py's
# _simulated_only_gate), reached from the Conversation Simulator only. Both
# EXTERNAL and INTERNAL profiles allowlist toee_identity_lookup (for
# match_phone/match_email_sender), so without this exclusion a live customer or
# copilot turn would expose link_identity to the model -- a prompt-injectable
# account-linking primitive. Still present in TOOL_CATALOG (so the HTTP
# dispatch surface's catalog validation accepts it) and in plugin.yaml's
# provides_tools (the manifest declares the full catalog surface); this only
# stops it reaching a live agent's tool-calling loop.
#
# toee_customer_memory.get_memory_audit (0.0.3 S20, FR-20) is excluded for the
# same reason, with a sharper stake: both EXTERNAL and INTERNAL allowlist
# toee_customer_memory, so without this exclusion the customer-facing model
# itself would gain a callable tool to read another customer's full write
# history, including employee actor_account_id -- exactly the admin-gated
# supervisor-only surface FR-20 exists to restrict. Reached only from the admin
# BFF's deterministic tools:dispatch call (over the internal_copilot profile's
# per-profile API, the only profile whose allowlist carries this tool).
#
# By contrast, toee_customer_memory.get_my_memory_summary (0.0.3 S21, FR-21) is
# deliberately NOT here: it's the verified-only customer self-service "what do
# you remember about me" read, meant to reach the EXTERNAL model's live
# tool-calling loop (its own verified-identity gate, not this list, is what
# keeps it safe -- see is_verified_customer_identity).
#
# toee_agent_experience.list_agent_experience (0.0.3 S22, FR-23) is excluded
# for the same reason as get_memory_audit: an admin-only read of the L6 store
# (proposed/confirmed/rejected entries, including proposer_context), meant only
# for the admin BFF's deterministic tools:dispatch call, never the copilot
# model's own tool-calling loop. propose_experience is deliberately NOT here --
# it's the governed write the S23 review fork calls.
#
# toee_agent_experience.confirm_experience / .reject_experience (0.0.3 S24,
# FR-24) are excluded for the same reason: the human confirm-gate decision --
# US23, the agent only "learns" what a human approved -- must never become a
# model-callable primitive the review fork (or a prompt injection) could use to
# self-approve its own proposals. Reached ONLY via the admin BFF's
# deterministic tools:dispatch call, never a live agent's tool loop.
_AGENT_EXCLUDED_ACTIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("toee_identity_lookup", "link_identity"),
        ("toee_customer_memory", "get_memory_audit"),
        ("toee_agent_experience", "list_agent_experience"),
        ("toee_agent_experience", "confirm_experience"),
        ("toee_agent_experience", "reject_experience"),
    }
)


def _build_driver_selector(
    injected: Optional[ToolDriver],
    extra_drivers: Optional[dict[str, ToolDriver]] = None,
) -> DriverSelector:
    """Resolve a per-tool driver selector (mock-first, ADR-0137).

    An ``injected`` driver (the eval recording path, :func:`register_eval`)
    overrides ALL tools and short-circuits backend resolution, so eval/replay never
    builds a live driver. Otherwise ``INTEGRATION_DRIVER`` selects the backend:
    ``mock`` (default) serves every tool, while ``composio`` routes only the three
    Layer 1 tools to the Composio driver and leaves the rest on mock (ADR-0128).

    ``extra_drivers`` is a per-tool override the embedding layer supplies for the
    live async turn (S04): precedence is ``extra_drivers[tool]`` -> composio ->
    mock, so ``toee_customer_memory`` reaches the Postgres datastore while every
    other tool keeps its backend. The override sits *inside* dispatch, after the
    catalog check, Tool Gate, and profile allowlist — so swapping the driver
    introduces no governance drift (the injected driver's ``kind`` attributes the
    audit record). psycopg never reaches the plugin: the embedding passes only an
    object satisfying the ``ToolDriver`` protocol.
    """
    if injected is not None:
        return lambda _tool: injected

    kind = resolve_integration_driver()
    mock_driver = MockDriver(create_all_mock_handlers())
    composio_driver = build_composio_driver() if kind == "composio" else None
    if kind not in ("mock", "composio"):
        raise NotImplementedError(
            f'Integration driver "{kind}" is not implemented yet (mock-first, ADR-0137).'
        )
    overrides = dict(extra_drivers or {})

    def select(tool: str) -> ToolDriver:
        if tool in overrides:
            return overrides[tool]
        if composio_driver is not None and tool in COMPOSIO_LAYER1_TOOLS:
            return composio_driver
        return mock_driver

    return select


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
    session_identity: Optional[Any] = None,
    memory_preferences: Optional[list[dict[str, Any]]] = None,
    extra_drivers: Optional[dict[str, ToolDriver]] = None,
) -> None:
    """Register a profile's allowlisted tools + the injection hook.

    The turn-binding gate (ADR-0107/0066) is the default gate; it is inert unless
    the context carries a ``conversation_id`` (eval/replay + Copilot paths are
    unbound), so only :func:`register_turn` activates the binding constraint. The
    Launch Eval recording path (:func:`register_eval`) injects the scenario's
    ``driver`` (its MockDriver) and ``gate`` (the External-profile gate) instead.
    ``extra_drivers`` is the live turn's per-tool driver override (S04), threaded
    into the selector so a chosen tool (e.g. ``toee_customer_memory``) reaches the
    datastore without changing governance.
    """
    profile = resolve_profile(ctx)
    allow = allowlisted_tools(profile)
    driver_for = _build_driver_selector(driver, extra_drivers)
    context_provider = provider_factory(profile)
    active_gate = gate if gate is not None else create_turn_binding_gate()

    for entry in build_tool_schemas():
        if entry["toolset"] not in allow:
            continue
        if (entry["tool"], entry["action"]) in _AGENT_EXCLUDED_ACTIONS:
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

    if session_identity is not None or memory_preferences:
        hook = make_pre_llm_call_hook(
            snapshot_provider=(
                (lambda _sid: session_identity) if session_identity is not None else None
            ),
            memory_provider=(
                (lambda _sid: memory_preferences) if memory_preferences else None
            ),
        )
    else:
        hook = make_pre_llm_call_hook()
    ctx.register_hook("pre_llm_call", hook)


def register(
    ctx: Any,
    *,
    identity: Optional[Any] = None,
    extra_drivers: Optional[dict[str, ToolDriver]] = None,
) -> None:
    """Register allowlisted Domain Adapter Tools + the injection hook for a profile.

    This is the Hermes plugin entry point (eval/replay + Copilot paths): the
    context carries no async turn binding, so the reply tool is unconstrained.

    ``identity`` threads the turn's Session Identity Snapshot into the (unbound)
    ToolExecutionContext so an identity-scoped write binds from context (S08): the
    Copilot draft turn resolves the case's thread identity and passes it here, and
    an employee-confirmed ``toee_customer_memory`` correction then binds to the SAME
    identity-derived key the turn-time read used. Absent (the plugin entry point and
    eval/replay call ``register(ctx)``) the context carries no identity, unchanged.

    ``extra_drivers`` is the SAME per-tool driver override ``register_turn`` has had
    since S04 (S20/PAC-4 gap #2): the Copilot draft turn is unbound (no
    ``conversation_id``), so without this an agent-initiated ``toee_customer_memory``
    write always fell to the ephemeral mock, even though S08 already binds the
    right identity. Threaded into :func:`_register` unchanged.
    """
    _register(
        ctx,
        provider_factory=lambda profile: _make_context_provider(
            profile, identity=identity
        ),
        extra_drivers=extra_drivers,
    )


def register_turn(
    ctx: Any,
    *,
    conversation_id: str,
    sms_session_id: Optional[str] = None,
    identity: Optional[Any] = None,
    memory_preferences: Optional[list[dict[str, Any]]] = None,
    extra_drivers: Optional[dict[str, ToolDriver]] = None,
) -> None:
    """Register for one async Textline turn bound to ``conversation_id`` (ADR-0107).

    The gateway embedding calls this after the internal job reloads + verifies the
    inbound binding; every governed dispatch then carries the binding, and the
    turn-binding gate rejects a ``toee_textline_reply.send_message`` aimed at any
    other conversation (ADR-0066). ``identity`` is the ingress Session Identity
    Snapshot (ADR-0043) closed over for Tool Gate authorization and ``pre_llm_call``
    injection (ADR-0140). ``extra_drivers`` is the per-tool driver override (S04)
    that routes ``toee_customer_memory`` to the Postgres datastore for this turn.
    """
    _register(
        ctx,
        provider_factory=lambda profile: _make_context_provider(
            profile,
            identity=identity,
            conversation_id=conversation_id,
            sms_session_id=sms_session_id,
        ),
        session_identity=identity,
        memory_preferences=memory_preferences,
        extra_drivers=extra_drivers,
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
        session_identity=identity,
    )


__all__ = ["register", "register_turn", "register_eval"]
