"""Production composition root for the Textline gateway (ADR-0095/0106/0107).

:func:`build_gateway_app` is the one place the gateway's seams are resolved from the
environment into the real production app. ``create_app`` and every factory below
stay seam-injectable for tests; this module is where the live collaborators are
assembled:

* the Textline webhook signing secret (ADR-0021) and the internal-job shared secret
  (ADR-0106), read from the environment;
* the real Textline outbound ``ReplySender`` (ADR-0083) — used for both the opt-out
  confirmation and the agent reply;
* the OpenRouter-backed governed, conversation-bound turn runner (ADR-0009/0107).

It fails closed: a missing secret raises at boot rather than allowing an
unauthenticated webhook, an unauthed model call, or a silently dropped reply. The
Textline and OpenRouter connections are resolved once here (fail-fast), so rotating
a credential requires a restart. The store uses Postgres when ``TOOL_BACKEND=datastore``
(same DB as Workbench Tier B); otherwise the in-memory defaults apply until Cloud
Tasks is wired (ADR-0105/0140).

Launch (the function is an ASGI app factory)::

    uvicorn hermes_runtime.gateway_composition:build_gateway_app --factory
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from toee_hermes.plugin.profiles import EXTERNAL, PROFILE_ENV_VAR

from hermes_runtime.gateway_app import create_app
from hermes_runtime.gateway_store import InMemoryGatewayStore
from hermes_runtime.job_dispatch import LocalDispatchingJobQueue
from hermes_runtime.openrouter import make_openrouter_run_turn, resolve_openrouter_config
from hermes_runtime.postgres_gateway_store import PostgresGatewayStore
from hermes_runtime.textline_reply import (
    make_textline_reply_sender,
    resolve_textline_config,
)
from hermes_runtime.tool_backend import resolve_tool_backend, select_tool_driver
from hermes_runtime.turn_runner import make_gateway_turn_runner

# Textline webhook signing secret (ADR-0021); consistent with TEXTLINE_ACCESS_TOKEN.
WEBHOOK_SECRET_ENV = "TEXTLINE_WEBHOOK_SECRET"

# Shared secret for the protected internal agent-turn route (ADR-0106); pairs with
# gateway_app.INTERNAL_JOB_SECRET_HEADER.
INTERNAL_JOB_SECRET_ENV = "INTERNAL_JOB_SECRET"

# Reply-sender gate (FR-10, NFR-4): unset/"textline" -> real Textline sender (token
# required); "simulated" -> no Textline POST, mirror still runs; anything else fails
# closed rather than falling through to the real sender.
REPLY_SENDER_ENV = "REPLY_SENDER"
_REPLY_SENDER_TEXTLINE = "textline"
_REPLY_SENDER_SIMULATED = "simulated"

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
            f"{name} is required to boot the Textline gateway; set it in the "
            "environment."
        )
    return value


def _simulated_reply_sender(conversation_id: str, body: str) -> None:
    """No-op ``ReplySender`` for ``REPLY_SENDER=simulated`` (NFR-4).

    Makes no Textline call and never raises, so the caller (:func:`make_gateway_turn_runner`
    in ``turn_runner.py``) proceeds to invoke ``on_reply_sent`` exactly as it would after a
    real send -- the reply still mirrors into ``message_turn`` for the simulator to read.
    """
    return None


def resolve_reply_sender():
    """Select the gateway's ``ReplySender`` from ``REPLY_SENDER`` (fail-closed, NFR-4).

    Unset or ``"textline"`` resolves the real Textline sender (``TEXTLINE_ACCESS_TOKEN``
    required). ``"simulated"`` returns a no-op sender -- the token is not required, and
    simulated traffic never reaches real Textline. Any other value raises immediately
    rather than silently falling through to the real sender.
    """
    value = (os.environ.get(REPLY_SENDER_ENV) or "").strip().lower()
    if value in ("", _REPLY_SENDER_TEXTLINE):
        return make_textline_reply_sender(config=resolve_textline_config())
    if value == _REPLY_SENDER_SIMULATED:
        return _simulated_reply_sender
    raise ValueError(
        f"{REPLY_SENDER_ENV}={value!r} is not recognized; expected 'textline' "
        "(or unset) for the real sender, or 'simulated' for the no-op sender."
    )


def build_gateway_app() -> FastAPI:
    """Assemble the production gateway app from the environment (fail-closed).

    Raises ``ValueError`` when any required secret is absent (webhook secret,
    internal-job secret, Textline access token, OpenRouter API key).
    """
    webhook_secret = _require_env(WEBHOOK_SECRET_ENV)
    internal_job_secret = _require_env(INTERNAL_JOB_SECRET_ENV)
    _apply_external_profile_env()

    # Resolved once at boot so a misconfiguration fails fast instead of on the first
    # webhook (rotation therefore requires a restart).
    reply_sender = resolve_reply_sender()
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
