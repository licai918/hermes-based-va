"""OpenRouter provider seam for the production async turn (ADR-0009, ADR-0139).

The gateway turn runner's only model boundary is ``run_turn``. In production it is
backed by OpenRouter: chat completions route through OpenRouter with the ADR-0009
pinned primary model. :func:`resolve_openrouter_config` reads the connection from
the environment (fail-closed when the key is absent), defaulting the base URL and
the primary model so a minimally-configured deployment is correct by construction.

These tests never call OpenRouter: configuration resolution is pure, and the
``run_turn`` wiring is exercised with an injected scripted OpenAI factory, so the
real network call is the only untested edge (it needs live credentials).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hermes_runtime.live import _scripted_openai_factory
from hermes_runtime.openrouter import (
    OPENROUTER_FALLBACK_MODEL,
    OPENROUTER_PRIMARY_MODEL,
    OpenRouterConfig,
    default_is_retryable,
    make_fallback_openai_factory,
    make_openrouter_run_turn,
    resolve_openrouter_config,
)
from hermes_runtime.turn_runner import outbound_reply_text

ENV_KEYS = (
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_MODEL",
    "OPENROUTER_FALLBACK_MODEL",
)


class _Boom(Exception):
    """A test-only retryable error standing in for an OpenRouter outage."""


@pytest.fixture(autouse=True)
def _clear_openrouter_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_resolve_defaults_to_openrouter_base_url_and_the_adr_pinned_primary_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-live")

    config = resolve_openrouter_config()

    assert config.api_key == "sk-or-live"
    assert config.base_url == "https://openrouter.ai/api/v1"
    assert config.model == OPENROUTER_PRIMARY_MODEL == "deepseek/deepseek-v4-pro"


def test_resolve_reads_base_url_and_model_overrides_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-live")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://proxy.internal/v1")
    monkeypatch.setenv("OPENROUTER_MODEL", "qwen/qwen3.6-flash")

    config = resolve_openrouter_config()

    assert config.base_url == "https://proxy.internal/v1"
    assert config.model == "qwen/qwen3.6-flash"


def test_resolve_raises_a_clear_error_when_the_api_key_is_absent() -> None:
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        resolve_openrouter_config()


def test_resolve_defaults_the_fallback_model_to_the_adr_pinned_secondary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-live")

    config = resolve_openrouter_config()

    assert config.fallback_model == OPENROUTER_FALLBACK_MODEL == "qwen/qwen3.6-flash"


def test_resolve_reads_a_fallback_model_override_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-live")
    monkeypatch.setenv("OPENROUTER_FALLBACK_MODEL", "meta/llama-guard")

    assert resolve_openrouter_config().fallback_model == "meta/llama-guard"


# --- G11a: make_fallback_openai_factory -----------------------------------


def _recording_client() -> SimpleNamespace:
    """A fake OpenAI client recording the model of each chat completion call."""
    client = SimpleNamespace(calls=[])

    def create(**kwargs: object) -> str:
        client.calls.append(kwargs.get("model"))
        return f"completion-from-{kwargs.get('model')}"

    client.chat = SimpleNamespace(completions=SimpleNamespace(create=create))
    return client


def test_fallback_factory_retries_on_the_fallback_model_for_a_retryable_error() -> None:
    client = _recording_client()
    original = client.chat.completions.create

    def failing_create(**kwargs: object) -> str:
        if not client.calls:
            client.calls.append(kwargs.get("model"))
            raise _Boom()
        return original(**kwargs)

    client.chat.completions.create = failing_create
    factory = make_fallback_openai_factory(
        base_factory=lambda *a, **k: client,
        fallback_model="qwen/fallback",
        is_retryable=lambda exc: isinstance(exc, _Boom),
    )

    result = factory().chat.completions.create(model="deepseek/primary", messages=[])

    assert result == "completion-from-qwen/fallback"
    assert client.calls == ["deepseek/primary", "qwen/fallback"]


def test_fallback_factory_propagates_a_non_retryable_error_without_retrying() -> None:
    client = _recording_client()

    def always_failing(**kwargs: object) -> str:
        client.calls.append(kwargs.get("model"))
        raise _Boom()

    client.chat.completions.create = always_failing
    factory = make_fallback_openai_factory(
        base_factory=lambda *a, **k: client,
        fallback_model="qwen/fallback",
        is_retryable=lambda exc: False,
    )

    with pytest.raises(_Boom):
        factory().chat.completions.create(model="deepseek/primary")

    assert client.calls == ["deepseek/primary"]


def test_fallback_factory_does_not_retry_when_the_primary_call_succeeds() -> None:
    client = _recording_client()
    factory = make_fallback_openai_factory(
        base_factory=lambda *a, **k: client,
        fallback_model="qwen/fallback",
        is_retryable=lambda exc: True,
    )

    result = factory().chat.completions.create(model="deepseek/primary")

    assert result == "completion-from-deepseek/primary"
    assert client.calls == ["deepseek/primary"]


# --- G11b: default_is_retryable -------------------------------------------


@pytest.mark.parametrize(
    "status,expected",
    [(429, True), (500, True), (502, True), (503, True), (400, False), (401, False), (404, False)],
)
def test_default_is_retryable_by_http_status(status: int, expected: bool) -> None:
    assert default_is_retryable(SimpleNamespace(status_code=status)) is expected


@pytest.mark.parametrize(
    "name,expected",
    [
        ("RateLimitError", True),
        ("APITimeoutError", True),
        ("APIConnectionError", True),
        ("InternalServerError", True),
        ("BadRequestError", False),
        ("AuthenticationError", False),
        ("ValueError", False),
    ],
)
def test_default_is_retryable_by_exception_type_name(name: str, expected: bool) -> None:
    exc = type(name, (Exception,), {})()

    assert default_is_retryable(exc) is expected


# --- G11c: make_openrouter_run_turn fallback wiring -----------------------


def test_make_openrouter_run_turn_falls_back_to_the_secondary_model_on_retryable() -> None:
    # The bound governed turn survives a retryable primary-model outage: the first
    # completion call fails, the fallback model serves it, and the rest of the loop
    # proceeds, so the customer still gets the governed reply (ADR-0009/0107).
    body = "We have your 225/65R17 in stock - want a payment link?"
    config = OpenRouterConfig(
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-or-test",
        model="deepseek/primary",
        fallback_model="qwen/fallback",
    )
    scripted = _scripted_openai_factory(
        [
            {
                "tool_calls": [
                    {
                        "name": "toee_textline_reply__send_message",
                        "arguments": {"conversation_id": "conv-A", "body": body},
                    }
                ]
            },
            {"content": "Done - texted the stock update."},
        ]
    )
    state = {"failed": False}

    def base_factory(*args: object, **kwargs: object) -> object:
        inner = scripted(*args, **kwargs)
        serve = inner.chat.completions.create

        def create(**call_kwargs: object) -> object:
            if not state["failed"]:
                state["failed"] = True
                raise _Boom()
            return serve(**call_kwargs)

        inner.chat.completions.create = create
        return inner

    run_turn = make_openrouter_run_turn(
        system_message="You are Toee Tire support.",
        config=config,
        openai_factory=base_factory,
        is_retryable=lambda exc: isinstance(exc, _Boom),
    )

    turn = run_turn(
        SimpleNamespace(conversation_id="conv-A", sms_session_id=None),
        "Got my size?",
    )

    assert outbound_reply_text(turn) == body


def test_make_openrouter_run_turn_runs_a_bound_governed_turn_via_injected_provider() -> None:
    # The production run_turn wiring: resolved OpenRouter config + a profile booted
    # bound to the conversation (ADR-0107) drive a real AIAgent loop and governed
    # dispatch. The provider is injected (scripted), so no network/credentials are
    # used; only the literal OpenRouter call is left untested.
    body = "Your order TOEE-1001 shipped today - tracking to follow."
    config = OpenRouterConfig(
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-or-test",
        model=OPENROUTER_PRIMARY_MODEL,
    )
    run_turn = make_openrouter_run_turn(
        system_message="You are Toee Tire support.",
        config=config,
        openai_factory=_scripted_openai_factory(
            [
                {
                    "tool_calls": [
                        {
                            "name": "toee_textline_reply__send_message",
                            "arguments": {"conversation_id": "conv-A", "body": body},
                        }
                    ]
                },
                {"content": "Done - I've texted you the update."},
            ]
        ),
    )

    turn = run_turn(
        SimpleNamespace(conversation_id="conv-A", sms_session_id=None),
        "Where is my order?",
    )

    assert outbound_reply_text(turn) == body
