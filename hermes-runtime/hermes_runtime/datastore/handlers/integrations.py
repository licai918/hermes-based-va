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

**Honest until S17.**
- ``last_successful_call`` is ``None`` everywhere: nothing in the drivers records one
  yet, so the panel shows "unknown" rather than a fabricated timestamp.
- ``last_probe`` (S16, FR-24): the LATEST ``integration_probe`` row per integration,
  ``{status, reason, checked_at}`` or ``None`` when no probe has run yet (the panel
  renders "never probed"). ``status`` is one of ``ok`` / ``failed`` /
  ``not_configured`` -- the three honest states the scheduled probe records; the page
  badges off it. A probe result is a status + reason string only, never a secret.

``conn`` is the deliberate S15 seam S16 fills: :func:`_latest_probes` SELECTs the
newest probe row per integration here. S17's reconnect reads the same
per-integration ``key`` this shape already carries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg.rows import dict_row

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
    last_probe: dict[str, Any] | None = None,
    pinned_version: str | None = None,
) -> dict[str, Any]:
    """One integration row in the uniform status shape.

    ``last_successful_call`` is always ``None`` (nothing records it yet -> "unknown").
    ``last_probe`` is the newest scheduled-probe row for this integration (S16) or
    ``None`` when none has run yet ("never probed") -- never a fabrication.
    """
    return {
        "key": key,
        "label": label,
        "kind": kind,
        "configured": configured,
        "status": "configured" if configured else "not_configured",
        "pinned_version": pinned_version,
        "last_successful_call": None,
        "last_probe": last_probe,
        "detail": detail,
    }


def _missing(env_name: str) -> str:
    return f"Not configured: set {env_name} in the deployment env."


def _latest_probes(conn) -> dict[str, dict[str, Any]]:
    """Newest ``integration_probe`` row per integration key (S16 seam, FR-24).

    Returns ``{key: {status, reason, checked_at}}``. ``conn`` is ``None`` only in the
    pure config-presence unit tests (which pass no DB); there the page has no probe
    history to show, so every ``last_probe`` stays ``None`` ("never probed").
    """
    if conn is None:
        return {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (integration_key)
                   integration_key, status, reason, checked_at
            FROM integration_probe
            ORDER BY integration_key, checked_at DESC
            """
        )
        rows = cur.fetchall()
    return {
        row["integration_key"]: {
            "status": row["status"],
            "reason": row["reason"],
            "checked_at": row["checked_at"].isoformat(),
        }
        for row in rows
    }


def _get_integrations_status(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    # A read -> no actor required, no audit (parity with get_retention_status).
    del params, context

    active_driver = resolve_integration_driver()
    composio = composio_config_status()
    probes = _latest_probes(conn)

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
                last_probe=probes.get(key),
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
            last_probe=probes.get("easyroutes"),
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
            last_probe=probes.get("simpletexting"),
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
            last_probe=probes.get("openrouter"),
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
            last_probe=probes.get("gadget"),
        )
    )

    return {"active_driver": active_driver, "integrations": integrations}


def integrations_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the integrations status-page read."""
    return {"toee_integrations": {"get_integrations_status": _get_integrations_status}}


__all__ = ["integrations_handlers"]
