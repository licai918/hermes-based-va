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

It fails closed: a missing secret -- or a ``TOOL_BACKEND`` that cannot serve the
durable turn path -- raises at boot rather than allowing an unauthenticated webhook,
an unauthed model call, or a silently dropped reply. The Textline and OpenRouter
connections are resolved once here (fail-fast), so rotating a credential requires a
restart. The store is Postgres, the same DB as Workbench Tier B (ADR-0140);
``resolve_turn_collaborators`` keeps an in-memory branch for the DB-free callers
that build the app directly.

Since 0.0.4 S02 the fast-ack path enqueues into the durable Postgres queue
(:class:`~hermes_runtime.job_queue.PostgresJobQueue`, ADR-0153) and the separate
``hermes_runtime.turn_worker`` process runs the turn -- the in-process
``LocalDispatchingJobQueue`` daemon thread is gone. :func:`resolve_turn_collaborators`
is the shared half both processes build.

Launch (the function is an ASGI app factory)::

    uvicorn hermes_runtime.gateway_composition:build_gateway_app --factory
    python -m hermes_runtime.turn_worker          # the other half
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, NamedTuple

from fastapi import FastAPI

from toee_hermes.plugin.profiles import EXTERNAL, PROFILE_ENV_VAR

from hermes_runtime.gateway_app import create_app
from hermes_runtime.gateway_store import InMemoryGatewayStore
from hermes_runtime.openrouter import make_openrouter_run_turn, resolve_openrouter_config
from hermes_runtime.postgres_gateway_store import PostgresGatewayStore
from hermes_runtime.textline_reply import (
    make_textline_reply_sender,
    resolve_textline_config,
)
from hermes_runtime.tool_backend import (
    TOOL_BACKEND_ENV,
    resolve_tool_backend,
    select_tool_driver,
)
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


class TurnCollaborators(NamedTuple):
    """The substrate a bound agent turn needs, resolved once from the environment.

    Shared by the two processes that run one: the gateway (for its internal
    Cloud-Tasks-parity route, ADR-0106) and the turn worker, which is where
    inbound turns actually execute after the 0.0.4 S02 cutover.
    """

    store: Any
    driver: Any
    turn_runner: Any
    reply_sender: Any


def resolve_turn_collaborators() -> TurnCollaborators:
    """Resolve the store, tool driver, reply sender and bound turn runner.

    Fails closed on a missing Textline token / OpenRouter key, and resolves both
    connections once so a misconfiguration surfaces at boot rather than on the
    first webhook (rotation therefore requires a restart).
    """
    _apply_external_profile_env()

    # S10 cold-load mitigation: nudges the fastembed model into memory in the
    # background so the first real knowledge query doesn't pay the ~800ms load
    # cost against the retrieval deadline. No-op when knowledge is disabled.
    from hermes_runtime.knowledge.driver import warm_knowledge_embedder

    warm_knowledge_embedder()

    reply_sender = resolve_reply_sender()
    run_turn = make_openrouter_run_turn(config=resolve_openrouter_config())

    # The store is the source of truth (ADR-0107): the turn worker reloads the
    # context the gateway persisted. When TOOL_BACKEND=datastore that is the same
    # Postgres Workbench reads (ADR-0140/0142); otherwise the in-memory substrate,
    # which is now single-process only -- see build_gateway_app.
    backend = resolve_tool_backend()
    if backend == "datastore":
        store = PostgresGatewayStore()
        driver = select_tool_driver("datastore")
    else:
        store = InMemoryGatewayStore()
        driver = None

    return TurnCollaborators(
        store=store,
        driver=driver,
        reply_sender=reply_sender,
        turn_runner=make_gateway_turn_runner(
            reply_sender=reply_sender,
            run_turn=run_turn,
            on_reply_sent=(
                (lambda ctx, text: store.persist_agent_outbound(ctx, text))
                if backend == "datastore"
                else None
            ),
        ),
    )


def _require_datastore_backend() -> None:
    """0.0.4 S02: ``TOOL_BACKEND=datastore`` is a boot requirement, not a preference.

    The gateway and the turn worker are two processes now. Only the shared Postgres
    store crosses between them, so with any other backend this app would still
    authenticate webhooks, persist into a per-process dict, and ack 200 -- while no
    worker could ever find the context and no customer would ever get a reply. That
    is exactly the silently dropped reply this module's fail-closed posture exists to
    prevent, so it raises here alongside the missing-secret checks.

    ``create_app``'s in-memory defaults are untouched: DB-free tests build the app
    directly, which is where booting without a database is a legitimate thing to do.
    """
    backend = resolve_tool_backend()
    if backend != "datastore":
        raise ValueError(
            f"{TOOL_BACKEND_ENV}={backend!r} cannot serve the durable turn path: the "
            "gateway persists the turn context and a separate turn-worker process "
            "reloads it, which only the shared datastore backend allows. Set "
            f"{TOOL_BACKEND_ENV}=datastore."
        )


def build_gateway_app() -> FastAPI:
    """Assemble the production gateway app from the environment (fail-closed).

    Raises ``ValueError`` when any required secret is absent (webhook secret,
    internal-job secret, Textline access token, OpenRouter API key) or when
    ``TOOL_BACKEND`` is not ``datastore``.
    """
    webhook_secret = _require_env(WEBHOOK_SECRET_ENV)
    internal_job_secret = _require_env(INTERNAL_JOB_SECRET_ENV)
    _require_datastore_backend()
    collaborators = resolve_turn_collaborators()

    # 0.0.4 S02 (FR-10, ADR-0153): fast-ack writes one durable `job` row instead of
    # spawning a daemon thread, and the turn-worker process claims it. The write
    # happens inside PostgresGatewayStore.persist_accepted_inbound's transaction --
    # there is no queue seam to wire here, because a seam here would be a second
    # commit boundary and a crash inside it loses an acked message (fix wave 1).
    return create_app(
        webhook_secret=webhook_secret,
        internal_job_secret=internal_job_secret,
        reply_sender=collaborators.reply_sender,
        turn_runner=collaborators.turn_runner,
        store=collaborators.store,
        driver=collaborators.driver,
        is_duplicate=collaborators.store.is_duplicate,
    )
