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
a credential requires a restart. The store and queue use the in-memory defaults
until the durable Postgres/Cloud Tasks substrate is wired (ADR-0105/0140).

Launch (the function is an ASGI app factory)::

    uvicorn hermes_runtime.gateway_composition:build_gateway_app --factory
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from hermes_runtime.gateway_app import create_app
from hermes_runtime.openrouter import make_openrouter_run_turn, resolve_openrouter_config
from hermes_runtime.textline_reply import (
    make_textline_reply_sender,
    resolve_textline_config,
)
from hermes_runtime.turn_runner import make_gateway_turn_runner

# Textline webhook signing secret (ADR-0021); consistent with TEXTLINE_ACCESS_TOKEN.
WEBHOOK_SECRET_ENV = "TEXTLINE_WEBHOOK_SECRET"

# Shared secret for the protected internal agent-turn route (ADR-0106); pairs with
# gateway_app.INTERNAL_JOB_SECRET_HEADER.
INTERNAL_JOB_SECRET_ENV = "INTERNAL_JOB_SECRET"


def _require_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise ValueError(
            f"{name} is required to boot the Textline gateway; set it in the "
            "environment."
        )
    return value


def build_gateway_app() -> FastAPI:
    """Assemble the production gateway app from the environment (fail-closed).

    Raises ``ValueError`` when any required secret is absent (webhook secret,
    internal-job secret, Textline access token, OpenRouter API key).
    """
    webhook_secret = _require_env(WEBHOOK_SECRET_ENV)
    internal_job_secret = _require_env(INTERNAL_JOB_SECRET_ENV)

    # Resolved once at boot so a misconfiguration fails fast instead of on the first
    # webhook (rotation therefore requires a restart).
    reply_sender = make_textline_reply_sender(config=resolve_textline_config())
    run_turn = make_openrouter_run_turn(config=resolve_openrouter_config())
    turn_runner = make_gateway_turn_runner(
        reply_sender=reply_sender, run_turn=run_turn
    )

    return create_app(
        webhook_secret=webhook_secret,
        internal_job_secret=internal_job_secret,
        reply_sender=reply_sender,
        turn_runner=turn_runner,
    )
