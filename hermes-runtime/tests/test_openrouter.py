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
    OPENROUTER_PRIMARY_MODEL,
    OpenRouterConfig,
    make_openrouter_run_turn,
    resolve_openrouter_config,
)
from hermes_runtime.turn_runner import outbound_reply_text

ENV_KEYS = ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "OPENROUTER_MODEL")


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
