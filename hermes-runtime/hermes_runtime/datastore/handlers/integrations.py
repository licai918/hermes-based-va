"""Datastore handler for ``toee_integrations`` -- the ``/admin/integrations``
status-page read (0.0.4 S15, FR-23).

**Admin-only, a credential surface.** ADR-0093 gives ``/admin/*`` supervisor+admin,
but the workbench narrows THIS page to admin-only (``lib/auth/access.ts``) --
deliberately narrower than the supervisor+admin dead-letter OPERATIONS view, because
integrations touch credentials (gap-review P4). Both actions are agent-excluded
(``_AGENT_EXCLUDED_ACTIONS``); this is reached only from the admin BFF's
deterministic ``tools:dispatch`` over the ``supervisor_admin`` profile.

**Honest config presence, no invented health.** Each integration's ``configured``
comes from that driver's OWN existing signal -- ``easyroutes_configured``,
``gadget_configured``, ``composio_config_status``, ``simpletexting_configured``,
``openrouter_configured`` -- read against THIS process's environment, which is the
same env the tool-executing processes share (docker-compose ``env_file``). So green
means the credential is actually present and a call would run, not merely that the
code path exists. An owner-blocked integration (no key yet) shows ``not_configured``,
never a fabricated ``healthy`` (the track's spine).

**No secret ever leaves.** Only booleans, the Composio version pin STRING (a version,
not a credential), and env-var NAMES are returned -- never a token/key/account-id
value. The repo secret-scan gate stays green (NFR-6).

**Honest until S16/S17.**
- ``last_successful_call`` is ``None`` everywhere: nothing in the drivers records one
  yet, so the panel shows "unknown" rather than a fabricated timestamp.
- ``last_probe`` is ``None`` everywhere: S16's scheduled probes fill it; the BFF/panel
  render "never probed" until then.

``conn`` is unused today -- the read needs no SQL. S16 adds a SELECT of the newest
probe row per integration here (this one handler is the deliberate seam), and S17's
reconnect reads the same per-integration ``key`` this shape already carries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from toee_hermes.drivers.base import resolve_integration_driver
from toee_hermes.drivers.composio.driver import composio_config_status
from toee_hermes.drivers.easyroutes.driver import (
    API_TOKEN_ENV as EASYROUTES_TOKEN_ENV,
    easyroutes_configured,
)
from toee_hermes.drivers.gadget import API_KEY_ENV as GADGET_KEY_ENV, gadget_configured

from hermes_runtime.openrouter import openrouter_configured
from hermes_runtime.simpletexting_reply import simpletexting_configured

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext

_OPENROUTER_KEY_ENV = "OPENROUTER_API_KEY"
_SIMPLETEXTING_TOKEN_ENV = "SIMPLETEXTING_API_TOKEN"

# Human labels for the three Composio Layer-1 toolkits (keys match
# composio_config_status()).
_COMPOSIO_LABELS = {
    "shopify": "Shopify (Composio)",
    "qbo": "QuickBooks (Composio)",
    "square": "Square (Composio)",
}


def _entry(
    *,
    key: str,
    label: str,
    kind: str,
    configured: bool,
    detail: str,
    pinned_version: str | None = None,
) -> dict[str, Any]:
    """One integration row in the uniform status shape.

    ``last_successful_call``/``last_probe`` are always ``None`` in S15 (see module
    docstring): the panel renders "unknown"/"never probed" -- never a fabrication.
    """
    return {
        "key": key,
        "label": label,
        "kind": kind,
        "configured": configured,
        "status": "configured" if configured else "not_configured",
        "pinned_version": pinned_version,
        "last_successful_call": None,
        "last_probe": None,
        "detail": detail,
    }


def _missing(env_name: str) -> str:
    return f"Not configured: set {env_name} in the deployment env."


def _get_integrations_status(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    # A read -> no actor required, no audit (parity with get_retention_status). No
    # SQL yet (S16 adds the probe SELECT); conn is accepted and ignored.
    del conn, params, context

    active_driver = resolve_integration_driver()
    composio = composio_config_status()

    integrations: list[dict[str, Any]] = []

    for key, label in _COMPOSIO_LABELS.items():
        status = composio[key]
        configured = bool(status["configured"])
        if configured:
            detail = f"Connected account present, pinned to {status['pinned_version']}."
        elif not status["api_key_present"]:
            detail = _missing("COMPOSIO_API_KEY")
        elif not status["connected"]:
            detail = _missing(str(status["account_env"]))
        else:
            detail = (
                f"Connected but no version pin: set {status['version_env']} to an "
                "exact toolkit version (not 'latest')."
            )
        integrations.append(
            _entry(
                key=key,
                label=label,
                kind="composio_toolkit",
                configured=configured,
                pinned_version=status["pinned_version"],  # type: ignore[arg-type]
                detail=detail,
            )
        )

    er_configured = easyroutes_configured()
    integrations.append(
        _entry(
            key="easyroutes",
            label="EasyRoutes",
            kind="easyroutes",
            configured=er_configured,
            detail=(
                "Delivery m2m credentials present."
                if er_configured
                else _missing(f"{EASYROUTES_TOKEN_ENV} and EASYROUTES_CLIENT_ID")
            ),
        )
    )

    st_configured = simpletexting_configured()
    integrations.append(
        _entry(
            key="simpletexting",
            label="SimpleTexting",
            kind="simpletexting",
            configured=st_configured,
            detail=(
                "Outbound SMS token present."
                if st_configured
                else _missing(_SIMPLETEXTING_TOKEN_ENV)
            ),
        )
    )

    or_configured = openrouter_configured()
    integrations.append(
        _entry(
            key="openrouter",
            label="OpenRouter",
            kind="openrouter",
            configured=or_configured,
            detail=(
                "Model API key present."
                if or_configured
                else _missing(_OPENROUTER_KEY_ENV)
            ),
        )
    )

    gadget_ok = gadget_configured()
    integrations.append(
        _entry(
            key="gadget",
            label="Gadget mapping endpoint (paymentstatussync)",
            kind="gadget",
            configured=gadget_ok,
            detail=(
                "QBO<->Shopify mapping API key present."
                if gadget_ok
                else _missing(GADGET_KEY_ENV)
            ),
        )
    )

    return {"active_driver": active_driver, "integrations": integrations}


def integrations_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the integrations status-page read."""
    return {"toee_integrations": {"get_integrations_status": _get_integrations_status}}


__all__ = ["integrations_handlers"]
