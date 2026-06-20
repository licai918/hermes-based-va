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

from ..drivers.base import resolve_integration_driver
from ..drivers.mock import MockDriver, create_all_mock_handlers
from ..execute import ToolDriver
from ..tool_gate import ToolExecutionContext
from .hooks import make_pre_llm_call_hook
from .profiles import allowlisted_tools, resolve_profile
from .schemas import build_tool_schemas
from .tools import ContextProvider, make_tool_handler


def _build_driver() -> ToolDriver:
    """Build the configured integration driver (mock-first, ADR-0137)."""
    kind = resolve_integration_driver()
    if kind == "mock":
        return MockDriver(create_all_mock_handlers())
    raise NotImplementedError(
        f'Integration driver "{kind}" is not implemented yet (mock-first, ADR-0137).'
    )


def _make_context_provider(profile: str) -> ContextProvider:
    """Bind the profile into a per-call execution-context builder.

    Identity-bearing kwargs (``identity``/``user_id``/``connected_account_id``)
    are read when the embedding layer passes them; until then the context carries
    the profile alone and identity-scoped reads see ``identity is None``.
    """

    def provider(kwargs: dict[str, Any]) -> ToolExecutionContext:
        return ToolExecutionContext(
            profile=profile,
            identity=kwargs.get("identity"),
            user_id=kwargs.get("user_id"),
            connected_account_id=kwargs.get("connected_account_id"),
        )

    return provider


def register(ctx: Any) -> None:
    """Register allowlisted Domain Adapter Tools + the injection hook for a profile."""
    profile = resolve_profile(ctx)
    allow = allowlisted_tools(profile)
    driver = _build_driver()
    context_provider = _make_context_provider(profile)

    for entry in build_tool_schemas():
        if entry["toolset"] not in allow:
            continue
        handler = make_tool_handler(
            tool=entry["tool"],
            action=entry["action"],
            driver=driver,
            context_provider=context_provider,
        )
        ctx.register_tool(
            name=entry["schema"]["name"],
            toolset=entry["toolset"],
            schema=entry["schema"],
            handler=handler,
        )

    ctx.register_hook("pre_llm_call", make_pre_llm_call_hook())


__all__ = ["register"]
