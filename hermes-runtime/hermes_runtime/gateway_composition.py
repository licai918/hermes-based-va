"""Production composition root for the SMS gateway (ADR-0095/0106/0107).

:func:`build_gateway_app` is the one place the gateway's seams are resolved from the
environment into the real production app. ``create_app`` and every factory below
stay seam-injectable for tests; this module is where the live collaborators are
assembled:

* the SimpleTexting webhook URL token (ADR-0021) and the internal-job shared secret
  (ADR-0106), read from the environment;
* the real SimpleTexting outbound ``ReplySender`` (ADR-0083) — used for both the
  opt-out confirmation and the agent reply;
* the OpenRouter-backed governed, conversation-bound turn runner (ADR-0009/0107).

It fails closed: a missing secret raises at boot rather than allowing an
unauthenticated webhook, an unauthed model call, or a silently dropped reply. The
SimpleTexting and OpenRouter connections are resolved once here (fail-fast), so
rotating a credential requires a restart. The store uses Postgres when
``TOOL_BACKEND=datastore`` (same DB as Workbench Tier B); otherwise the in-memory
defaults apply until Cloud Tasks is wired (ADR-0105/0140).

Launch (the function is an ASGI app factory)::

    uvicorn hermes_runtime.gateway_composition:build_gateway_app --factory
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from toee_hermes.plugin.profiles import EXTERNAL, PROFILE_ENV_VAR

from hermes_runtime.access_log import install_access_log_redaction
from hermes_runtime.gateway_app import create_app
from hermes_runtime.gateway_store import InMemoryGatewayStore
from hermes_runtime.job_dispatch import LocalDispatchingJobQueue
from hermes_runtime.openrouter import make_openrouter_run_turn, resolve_openrouter_config
from hermes_runtime.postgres_gateway_store import PostgresGatewayStore
from hermes_runtime.simpletexting_reply import (
    make_simpletexting_reply_sender,
    resolve_simpletexting_config,
)
from hermes_runtime.tool_backend import resolve_tool_backend, select_tool_driver
from hermes_runtime.turn_runner import make_gateway_turn_runner

# SimpleTexting webhook URL token (ADR-0021): SimpleTexting does not sign payloads,
# so the registered webhook URL carries ?token=<this secret>.
WEBHOOK_SECRET_ENV = "SIMPLETEXTING_WEBHOOK_TOKEN"

# Shared secret for the protected internal agent-turn route (ADR-0106); pairs with
# gateway_app.INTERNAL_JOB_SECRET_HEADER.
INTERNAL_JOB_SECRET_ENV = "INTERNAL_JOB_SECRET"

# Where this process runs. Unset = local development (in-memory substrate is fine).
# Set it on every deployed revision so the replay-protection guard below applies.
DEPLOY_ENV = "DEPLOY_ENVIRONMENT"
_PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod", "staging"})

# Canonical External profile home (ADR-0139): restricts Hermes built-ins to the
# customer-service tool surface configured in hermes/profiles/customer_service_external.
_EXTERNAL_PROFILE_HOME = (
    Path(__file__).resolve().parents[2] / "hermes" / "profiles" / EXTERNAL
)


def _apply_external_profile_env() -> None:
    """Point Hermes at the External Customer Service profile home (ADR-0139/0034)."""
    os.environ["HERMES_HOME"] = str(_EXTERNAL_PROFILE_HOME)
    os.environ[PROFILE_ENV_VAR] = EXTERNAL


def _require_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise ValueError(
            f"{name} is required to boot the SMS gateway; set it in the "
            "environment."
        )
    return value


def _deploy_environment() -> str:
    """Resolve where the gateway is running; unset means local development."""
    return (os.environ.get(DEPLOY_ENV) or "").strip().lower()


def _require_in_memory_store_is_allowed() -> None:
    """Refuse to serve real traffic on a per-process dedup store (ADR-0149).

    SimpleTexting does not sign webhooks, so replay protection rests entirely on
    messageId idempotency. With the in-memory store that dedup is a dict inside one
    process: Cloud Run autoscaling sends a replay to a different instance, and
    scale-to-zero wipes it, so every captured request stays replayable forever.
    Fail at boot rather than serve production traffic with no replay protection.
    """
    environment = _deploy_environment()
    if environment in _PRODUCTION_ENVIRONMENTS:
        raise ValueError(
            f"{DEPLOY_ENV}={environment} requires TOOL_BACKEND=datastore: the "
            "in-memory store dedups per process, which leaves inbound webhooks "
            "replayable across instances and restarts (ADR-0149)."
        )


def build_gateway_app() -> FastAPI:
    """Assemble the production gateway app from the environment (fail-closed).

    Raises ``ValueError`` when any required secret is absent (webhook token,
    internal-job secret, SimpleTexting API token, OpenRouter API key), or when a
    deployed environment is configured with the in-memory (per-process) store.
    """
    # Before anything can serve a request: the webhook token rides in the URL
    # (SimpleTexting offers no header/signature option), and uvicorn's access log
    # would otherwise write it verbatim into Cloud Logging (ADR-0149).
    install_access_log_redaction()

    webhook_secret = _require_env(WEBHOOK_SECRET_ENV)
    internal_job_secret = _require_env(INTERNAL_JOB_SECRET_ENV)
    _apply_external_profile_env()

    # Resolved once at boot so a misconfiguration fails fast instead of on the first
    # webhook (rotation therefore requires a restart).
    reply_sender = make_simpletexting_reply_sender(config=resolve_simpletexting_config())
    run_turn = make_openrouter_run_turn(config=resolve_openrouter_config())

    # The store is the source of truth (ADR-0107); the local dispatcher reloads from
    # the same instance the internal route uses. When TOOL_BACKEND=datastore, persist
    # into the same Postgres Workbench reads (ADR-0140/0142); otherwise the in-memory
    # substrate (ADR-0105 local dev without Docker).
    backend = resolve_tool_backend()
    if backend == "datastore":
        store = PostgresGatewayStore()
        driver = select_tool_driver("datastore")
    else:
        _require_in_memory_store_is_allowed()
        store = InMemoryGatewayStore()
        driver = None

    turn_runner = make_gateway_turn_runner(
        reply_sender=reply_sender,
        run_turn=run_turn,
        on_reply_sent=(
            (lambda ctx, text: store.persist_agent_outbound(ctx, text))
            if backend == "datastore"
            else None
        ),
    )

    queue = LocalDispatchingJobQueue(store=store, turn_runner=turn_runner)

    return create_app(
        webhook_secret=webhook_secret,
        internal_job_secret=internal_job_secret,
        reply_sender=reply_sender,
        turn_runner=turn_runner,
        store=store,
        queue=queue,
        driver=driver,
        is_duplicate=store.is_duplicate,
    )
