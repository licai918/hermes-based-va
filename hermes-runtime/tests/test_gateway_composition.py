"""Production composition root: build_gateway_app() (ADR-0095/0106/0107/0009/0083).

Everything below the gateway is a seam (reply sender, run_turn, store, queue) so the
HTTP app stays testable with fakes. :func:`build_gateway_app` is the one place those
seams are resolved from the environment into the *real* production app: the Textline
webhook signing secret (ADR-0021), the internal-job shared secret (ADR-0106), the
real Textline ReplySender (ADR-0083), and the OpenRouter-backed governed turn runner
(ADR-0009/0107).

The root fails closed: a missing secret raises at boot, never a silent
fall-through to an unauthenticated webhook, an unauthed model call, or a dropped
reply. These tests pin that contract and that the resolved collaborators are wired
into ``create_app`` — without any network call (configs are read at boot; the real
HTTP/model calls are lazy and never fire here).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from hermes_runtime.gateway_composition import (
    INTERNAL_JOB_SECRET_ENV,
    WEBHOOK_SECRET_ENV,
    build_gateway_app,
)
from hermes_runtime.job_dispatch import LocalDispatchingJobQueue

# Every env var a correctly-configured deployment must set.
REQUIRED_ENV = {
    WEBHOOK_SECRET_ENV: "whsec-123",
    INTERNAL_JOB_SECRET_ENV: "job-secret-123",
    "TEXTLINE_ACCESS_TOKEN": "tok-123",
    "OPENROUTER_API_KEY": "or-key-123",
}

# Optional env that would otherwise leak from the developer's shell.
_OPTIONAL_ENV = ("TEXTLINE_API_BASE_URL", "OPENROUTER_BASE_URL", "OPENROUTER_MODEL")


@pytest.fixture
def _full_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _OPTIONAL_ENV:
        monkeypatch.delenv(key, raising=False)
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


def test_build_gateway_app_returns_a_real_app_with_both_routes(
    _full_env: None,
) -> None:
    app = build_gateway_app()

    assert isinstance(app, FastAPI)
    paths = {route.path for route in app.routes}
    assert "/webhooks/textline" in paths
    assert "/internal/jobs/agent-turn" in paths


def test_build_gateway_app_wires_resolved_secrets_and_collaborators(
    _full_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}

    def _spy_create_app(**kwargs: object) -> FastAPI:
        captured.update(kwargs)
        return FastAPI()

    monkeypatch.setattr(
        "hermes_runtime.gateway_composition.create_app", _spy_create_app
    )

    build_gateway_app()

    assert captured["webhook_secret"] == "whsec-123"
    assert captured["internal_job_secret"] == "job-secret-123"
    # The real Textline sender and the OpenRouter-backed turn runner are both wired.
    assert callable(captured["reply_sender"])
    assert callable(captured["turn_runner"])


def test_build_gateway_app_wires_a_local_dispatcher_sharing_the_route_store(
    _full_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}

    def _spy_create_app(**kwargs: object) -> FastAPI:
        captured.update(kwargs)
        return FastAPI()

    monkeypatch.setattr(
        "hermes_runtime.gateway_composition.create_app", _spy_create_app
    )

    build_gateway_app()

    # Locally there is no Cloud Tasks, so the queue itself drives the turn (ADR-0105
    # local substrate) against the same store the internal route reloads from.
    assert isinstance(captured["queue"], LocalDispatchingJobQueue)
    assert captured["store"] is not None
    assert captured["queue"]._store is captured["store"]


def test_build_gateway_app_wires_postgres_store_when_tool_backend_is_datastore(
    _full_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}

    def _spy_create_app(**kwargs: object) -> FastAPI:
        captured.update(kwargs)
        return FastAPI()

    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.setattr(
        "hermes_runtime.gateway_composition.create_app", _spy_create_app
    )

    build_gateway_app()

    from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

    assert isinstance(captured["store"], PostgresGatewayStore)
    assert captured["driver"] is not None
    assert callable(captured["is_duplicate"])


@pytest.mark.parametrize("missing", list(REQUIRED_ENV))
def test_build_gateway_app_fails_closed_when_a_required_secret_is_absent(
    _full_env: None, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.delenv(missing, raising=False)

    with pytest.raises(ValueError, match=missing):
        build_gateway_app()
