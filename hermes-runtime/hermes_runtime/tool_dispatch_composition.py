"""Composition root for a per-profile tool-dispatch server (ADR-0141, Slice 34).

:func:`build_tool_dispatch_app` is the one place the deterministic
``tools:dispatch`` app is resolved from the environment into a runnable
per-profile service. One process runs per profile (its own ``TOEE_HERMES_PROFILE``
and ``DISPATCH_API_TOKEN``), reachable by the workbench BFF over
``http://localhost:<port>`` (ADR-0142 local-first; Cloud Run packaging is Slice 37).

It fails closed, like :func:`hermes_runtime.gateway_composition.build_gateway_app`:
a missing/unknown profile or a missing bearer token raises at boot rather than
booting a server that would expose the wrong toolset or an unauthenticated
dispatch route. The tool backend is mock-first and selected on its own axis by
``TOOL_BACKEND`` (ADR-0137/0140) via :func:`select_tool_driver`, so the same server
boots against the MockDriver locally and the Postgres datastore when configured.

Launch (the function is an ASGI app factory)::

    uvicorn hermes_runtime.tool_dispatch_composition:build_tool_dispatch_app --factory
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from toee_hermes.plugin.profiles import INTERNAL, PROFILE_ENV_VAR, PROFILES

from hermes_runtime.agent_turn_app import add_agent_turn_route
from hermes_runtime.tool_backend import select_tool_driver
from hermes_runtime.tool_dispatch_app import create_tool_dispatch_app

# Per-process bearer the BFF presents (ADR-0141). One token per profile home; the
# operator sets the BFF's HERMES_COPILOT_API_TOKEN / HERMES_ADMIN_API_TOKEN to the
# matching server's value. Generic name (the profile selector differentiates the
# homes), mirroring the gateway's single-secret env vars.
DISPATCH_API_TOKEN_ENV = "DISPATCH_API_TOKEN"


def _require_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise ValueError(
            f"{name} is required to boot the tool-dispatch server; set it in the "
            "environment."
        )
    return value


def build_tool_dispatch_app() -> FastAPI:
    """Assemble the per-profile dispatch app from the environment (fail-closed).

    Raises ``ValueError`` when the profile selector is absent or unknown, or when
    the per-process bearer token is absent.
    """
    profile = _require_env(PROFILE_ENV_VAR)
    if profile not in PROFILES:
        raise ValueError(
            f'Unknown {PROFILE_ENV_VAR} "{profile}". '
            f"Expected one of: {', '.join(PROFILES)}."
        )
    api_token = _require_env(DISPATCH_API_TOKEN_ENV)

    # TOOL_BACKEND=mock (default) or datastore (ADR-0140) selects the driver once,
    # shared by both routes so the agent:turn audit (option i, #47) lands in the same
    # store the dispatch reads/writes use. The profile-allowlist gate is the default
    # inside create_tool_dispatch_app, so the deployment's fixed profile bounds the
    # surface.
    driver = select_tool_driver()
    app = create_tool_dispatch_app(api_token=api_token, profile=profile, driver=driver)
    # ADR-0147 Fork A1 + M3: the agent:turn LLM draft seam is mounted ONLY on the
    # copilot (INTERNAL) server — "the copilot server" the ADR scopes it to. The
    # SUPERVISOR/EXTERNAL dispatch servers expose tools:dispatch but NOT this LLM
    # route, so the draft capability can't be reached on a server that should never
    # draft (the deterministic dispatch app stays LLM-free everywhere). On the copilot
    # server the route boots internal_copilot unbound (structurally no-send,
    # ADR-0035/0067) and the shared driver records the draft_generated audit
    # server-side (#47, option i); mock-mode is a no-op sink.
    if profile == INTERNAL:
        add_agent_turn_route(app, api_token=api_token, driver=driver)
    return app
