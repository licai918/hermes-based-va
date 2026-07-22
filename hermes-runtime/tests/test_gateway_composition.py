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

import os

import pytest
from fastapi import FastAPI

from hermes_runtime.gateway_composition import (
    INTERNAL_JOB_SECRET_ENV,
    REPLY_SENDER_ENV,
    WEBHOOK_SECRET_ENV,
    build_gateway_app,
    resolve_reply_sender,
)

# Every env var a correctly-configured deployment must set. TOOL_BACKEND is one of
# them since 0.0.4 S02: the gateway and the turn worker are separate processes, so
# only the shared datastore backend can carry a turn between them (see
# test_build_gateway_app_fails_closed_when_a_required_secret_is_absent, which
# parametrizes over this dict and therefore covers it).
REQUIRED_ENV = {
    WEBHOOK_SECRET_ENV: "whsec-123",
    INTERNAL_JOB_SECRET_ENV: "job-secret-123",
    "TEXTLINE_ACCESS_TOKEN": "tok-123",
    "OPENROUTER_API_KEY": "or-key-123",
    "TOOL_BACKEND": "datastore",
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


def test_build_gateway_app_wires_the_durable_path_without_touching_postgres(
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

    # 0.0.4 S02 (FR-10, ADR-0155): the fast-ack path writes one durable `job` row
    # and the separate turn-worker process runs the turn. No in-process dispatcher
    # remains -- and no `queue` seam either: the enqueue happens inside the store's
    # persist transaction, because a seam here would be a second commit boundary a
    # crash could fall into after the webhook was already acked (fix wave 1).
    assert "queue" not in captured
    assert captured["store"] is not None
    # The pool is lazy: wiring this must not have opened a connection at boot, which
    # is what keeps `build_gateway_app()` bootable with no database running.
    import hermes_runtime.datastore.pool as db_pool_mod

    assert db_pool_mod._pools == {}


def test_build_gateway_app_fails_closed_on_a_tool_backend_that_cannot_reply(
    _full_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The in-memory store cannot cross the gateway/worker process boundary, so a
    gateway booted on it would authenticate, persist, ack 200 -- and never reply.
    That is the silently dropped reply this composition root refuses to allow."""
    monkeypatch.setenv("TOOL_BACKEND", "mock")

    with pytest.raises(ValueError, match="TOOL_BACKEND"):
        build_gateway_app()


def test_build_gateway_app_wires_postgres_store_when_tool_backend_is_datastore(
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

    from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

    assert isinstance(captured["store"], PostgresGatewayStore)
    assert captured["driver"] is not None
    assert callable(captured["is_duplicate"])


def test_build_gateway_app_applies_external_profile_home(
    _full_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in ("HERMES_HOME", "TOEE_HERMES_PROFILE"):
        monkeypatch.delenv(key, raising=False)

    build_gateway_app()

    from toee_hermes.plugin.profiles import EXTERNAL, PROFILE_ENV_VAR

    assert os.environ.get(PROFILE_ENV_VAR) == EXTERNAL
    assert EXTERNAL in (os.environ.get("HERMES_HOME") or "")


def test_clip_sms_reply_truncates_long_agent_text() -> None:
    from hermes_runtime.turn_runner import clip_sms_reply

    long_text = "word " * 200
    clipped = clip_sms_reply(long_text)
    assert len(clipped) <= 480
    assert clipped.endswith("…")


@pytest.mark.parametrize("missing", list(REQUIRED_ENV))
def test_build_gateway_app_fails_closed_when_a_required_secret_is_absent(
    _full_env: None, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.delenv(missing, raising=False)

    with pytest.raises(ValueError, match=missing):
        build_gateway_app()


# --- S01: REPLY_SENDER composition gate (FR-10, NFR-4) ---------------------


def test_resolve_reply_sender_defaults_to_real_textline_sender_and_requires_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(REPLY_SENDER_ENV, raising=False)
    monkeypatch.delenv("TEXTLINE_ACCESS_TOKEN", raising=False)

    with pytest.raises(ValueError, match="TEXTLINE_ACCESS_TOKEN"):
        resolve_reply_sender()


def test_resolve_reply_sender_textline_value_behaves_like_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(REPLY_SENDER_ENV, "textline")
    monkeypatch.setenv("TEXTLINE_ACCESS_TOKEN", "tok-123")

    sender = resolve_reply_sender()

    assert callable(sender)


def test_resolve_reply_sender_simulated_does_not_require_a_textline_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(REPLY_SENDER_ENV, "simulated")
    monkeypatch.delenv("TEXTLINE_ACCESS_TOKEN", raising=False)

    sender = resolve_reply_sender()

    assert callable(sender)


def test_resolve_reply_sender_simulated_makes_no_network_call_and_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(REPLY_SENDER_ENV, "simulated")
    monkeypatch.delenv("TEXTLINE_ACCESS_TOKEN", raising=False)

    def _boom(*args: object, **kwargs: object) -> int:
        raise AssertionError("simulated sender must never open a network connection")

    monkeypatch.setattr("hermes_runtime.textline_reply._urllib_post", _boom)

    sender = resolve_reply_sender()

    assert sender("conv-A", "Hello") is None


def test_resolve_reply_sender_unrecognized_value_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(REPLY_SENDER_ENV, "bogus")
    monkeypatch.delenv("TEXTLINE_ACCESS_TOKEN", raising=False)

    # The error must name the misconfiguration, not the (irrelevant, unset) Textline
    # token -- proof this never silently falls through to the real sender.
    with pytest.raises(ValueError, match="REPLY_SENDER"):
        resolve_reply_sender()


def test_build_gateway_app_wires_simulated_reply_sender_without_textline_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in _OPTIONAL_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(WEBHOOK_SECRET_ENV, "whsec-123")
    monkeypatch.setenv(INTERNAL_JOB_SECRET_ENV, "job-secret-123")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key-123")
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.delenv("TEXTLINE_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv(REPLY_SENDER_ENV, "simulated")

    app = build_gateway_app()

    assert isinstance(app, FastAPI)


def test_build_gateway_app_fails_closed_on_unrecognized_reply_sender(
    _full_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(REPLY_SENDER_ENV, "bogus")

    with pytest.raises(ValueError, match="REPLY_SENDER"):
        build_gateway_app()


def test_simulated_reply_sender_still_mirrors_via_on_reply_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance: simulated sender -> no send error, success result, mirror runs."""
    from types import SimpleNamespace

    from hermes_runtime.turn_runner import make_gateway_turn_runner

    monkeypatch.setenv(REPLY_SENDER_ENV, "simulated")
    monkeypatch.delenv("TEXTLINE_ACCESS_TOKEN", raising=False)
    sender = resolve_reply_sender()

    mirrored: list[tuple[object, str]] = []
    runner = make_gateway_turn_runner(
        reply_sender=sender,
        run_turn=lambda context, body: {
            "final_response": "Shipped!",
            "messages": [],
        },
        on_reply_sent=lambda ctx, text: mirrored.append((ctx, text)),
    )
    ctx = SimpleNamespace(event_id="evt-A", conversation_id="conv-A")

    runner(ctx, "Where is my order?", "job-A")

    assert mirrored == [(ctx, "Shipped!")]
