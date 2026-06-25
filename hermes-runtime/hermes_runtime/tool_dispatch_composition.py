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

from toee_hermes.plugin.profiles import PROFILE_ENV_VAR, PROFILES

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

    # Driver defaults to select_tool_driver() inside create_tool_dispatch_app:
    # TOOL_BACKEND=mock (default) or datastore (ADR-0140). The profile-allowlist
    # gate is the default, so the deployment's fixed profile bounds the surface.
    return create_tool_dispatch_app(api_token=api_token, profile=profile)
