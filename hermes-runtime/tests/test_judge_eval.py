"""The live judge client seam for the S08 advisory command (no network in tests).

Mirrors ``test_record_suite.py``'s ``test_make_openrouter_record_run_drives_the_real_loop_via_injected_provider``:
an injected ``openai_factory`` fake stands in for the real OpenAI client, so this
proves ``OpenRouterJudgeClient`` builds the request correctly and returns the
completion's text -- no real OpenRouter call, no ``OPENROUTER_API_KEY`` needed.
"""

from __future__ import annotations

from hermes_runtime.judge_eval import OpenRouterJudgeClient


def _fake_openai_factory(captured: dict[str, object]):
    class _Completions:
        def create(self, **kwargs: object):
            captured["kwargs"] = kwargs
            from openai.types.chat import ChatCompletion
            from openai.types.chat.chat_completion import Choice
            from openai.types.chat.chat_completion_message import ChatCompletionMessage

            return ChatCompletion(
                id="x",
                created=0,
                model="m",
                object="chat.completion",
                choices=[
                    Choice(
                        index=0,
                        finish_reason="stop",
                        message=ChatCompletionMessage(
                            role="assistant",
                            content='{"verdict": "yes", "reason": "ok"}',
                        ),
                    )
                ],
            )

    class _Chat:
        def __init__(self) -> None:
            self.completions = _Completions()

    class _Client:
        def __init__(self, *_a: object, **kwargs: object) -> None:
            captured["client_kwargs"] = kwargs
            self.chat = _Chat()

    return _Client


def test_complete_sends_the_prompt_and_model_and_returns_the_content() -> None:
    captured: dict[str, object] = {}
    client = OpenRouterJudgeClient(
        base_url="http://router.invalid/v1",
        api_key="sk-test",
        openai_factory=_fake_openai_factory(captured),
    )

    text = client.complete("judge this reply", model="anthropic/claude-haiku-4.5")

    assert text == '{"verdict": "yes", "reason": "ok"}'
    assert captured["kwargs"]["model"] == "anthropic/claude-haiku-4.5"
    assert captured["kwargs"]["messages"] == [
        {"role": "user", "content": "judge this reply"}
    ]


def test_client_is_constructed_against_the_given_base_url_and_key() -> None:
    captured: dict[str, object] = {}
    OpenRouterJudgeClient(
        base_url="http://router.invalid/v1",
        api_key="sk-test",
        openai_factory=_fake_openai_factory(captured),
    )

    assert captured["client_kwargs"] == {
        "base_url": "http://router.invalid/v1",
        "api_key": "sk-test",
    }


def test_missing_content_degrades_to_empty_string_not_a_crash() -> None:
    captured: dict[str, object] = {}

    class _Completions:
        def create(self, **kwargs: object):
            from openai.types.chat import ChatCompletion
            from openai.types.chat.chat_completion import Choice
            from openai.types.chat.chat_completion_message import ChatCompletionMessage

            return ChatCompletion(
                id="x",
                created=0,
                model="m",
                object="chat.completion",
                choices=[
                    Choice(
                        index=0,
                        finish_reason="stop",
                        message=ChatCompletionMessage(role="assistant", content=None),
                    )
                ],
            )

    class _Chat:
        def __init__(self) -> None:
            self.completions = _Completions()

    class _Client:
        def __init__(self, *_a: object, **_k: object) -> None:
            self.chat = _Chat()

    client = OpenRouterJudgeClient(
        base_url="http://router.invalid/v1", api_key="sk-test", openai_factory=_Client
    )

    assert client.complete("x", model="m") == ""
