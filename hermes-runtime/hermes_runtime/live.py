"""Bridge a real Nous ``hermes-agent`` turn into the record/replay harness.

A live turn is driven by a deterministic provider seam (scripted ChatCompletions)
so the eval harness captures ``{final_response, messages}`` from a *real*
``AIAgent`` loop with no model, network, or credentials, then hands it to
:func:`eval_runner.recorder.record_turn` for deterministic replay (ADR-0121,
ADR-0139). The provider is the only fake — the unavoidable nondeterministic
boundary; the agent loop, governed tool dispatch, and turn capture are real.

The agent is forced onto its non-streaming path (``_disable_streaming``): the
streaming path consumes ``create()`` as a chunk iterator, whereas the documented
non-streaming fallback returns a plain ``ChatCompletion`` we can script
deterministically.

When a ``profile`` is given, the profile's allowlisted governed ``toee_*`` tools
are booted into Hermes' global tool registry (:func:`hermes_runtime.boot.boot_profile`)
and admitted to the agent's ``valid_tool_names``, so a scripted tool call dispatches
through real governed execution (catalog check, Tool Gate, driver, audit; ADR-0034).
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Mapping, Sequence


def _text_completion(content: str) -> Any:
    """A ``ChatCompletion`` carrying one assistant text reply (terminal turn)."""
    from openai.types.chat import ChatCompletion
    from openai.types.chat.chat_completion import Choice
    from openai.types.chat.chat_completion_message import ChatCompletionMessage

    return ChatCompletion(
        id="eval-fake",
        created=0,
        model="eval-fake-model",
        object="chat.completion",
        choices=[
            Choice(
                index=0,
                finish_reason="stop",
                message=ChatCompletionMessage(role="assistant", content=content),
            )
        ],
    )


def _tool_calls_completion(tool_calls: Sequence[Mapping[str, Any]]) -> Any:
    """A ``ChatCompletion`` whose assistant message requests governed tool calls."""
    from openai.types.chat import ChatCompletion
    from openai.types.chat.chat_completion import Choice
    from openai.types.chat.chat_completion_message import ChatCompletionMessage
    from openai.types.chat.chat_completion_message_tool_call import (
        ChatCompletionMessageToolCall,
        Function,
    )

    calls = [
        ChatCompletionMessageToolCall(
            id=spec.get("id") or f"call_{index}",
            type="function",
            function=Function(
                name=str(spec["name"]),
                arguments=json.dumps(spec.get("arguments") or {}),
            ),
        )
        for index, spec in enumerate(tool_calls)
    ]
    return ChatCompletion(
        id="eval-fake",
        created=0,
        model="eval-fake-model",
        object="chat.completion",
        choices=[
            Choice(
                index=0,
                finish_reason="tool_calls",
                message=ChatCompletionMessage(
                    role="assistant", content=None, tool_calls=calls
                ),
            )
        ],
    )


def _completion_from_spec(spec: Mapping[str, Any]) -> Any:
    """Build one scripted ``ChatCompletion`` from a ``{content}`` or ``{tool_calls}`` spec."""
    if spec.get("tool_calls") is not None:
        return _tool_calls_completion(spec["tool_calls"])
    return _text_completion(str(spec.get("content", "")))


def _scripted_openai_factory(completions: Sequence[Mapping[str, Any]]) -> type:
    """An ``OpenAI``-shaped class whose ``chat.completions.create`` is scripted.

    The agent builds a fresh request client per call, so the scripted responses
    live in a queue closed over here (shared across every client instance) and are
    served in order. An exhausted queue raises rather than silently looping.
    """
    queue = [_completion_from_spec(spec) for spec in completions]

    class _Completions:
        def create(self, **_kwargs: Any) -> Any:
            if not queue:
                raise RuntimeError("scripted completions exhausted")
            return queue.pop(0)

    class _Chat:
        def __init__(self) -> None:
            self.completions = _Completions()

    class _ScriptedOpenAI:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.chat = _Chat()

    return _ScriptedOpenAI


def run_agent_turn(
    *,
    user_message: str,
    system_message: str | None = None,
    base_url: str,
    api_key: str,
    model: str,
    max_iterations: int,
    openai_factory: Any = None,
    governed_tool_names: Sequence[str] = (),
) -> dict[str, Any]:
    """Drive one real ``AIAgent`` turn against the given provider; capture the turn.

    The agent is forced non-streaming and built with the given connection params.
    ``openai_factory`` is the provider seam: when given it replaces ``run_agent.OpenAI``
    for the turn (a deterministic scripted client in tests/eval); when ``None`` the
    real OpenAI client is used, pointed at ``base_url`` (production OpenRouter,
    ADR-0009). ``governed_tool_names`` (the booted profile's tools) are admitted to
    ``valid_tool_names`` so tool calls dispatch through real governed execution.

    Returns ``{"final_response": str, "messages": list}`` — the exact shape
    :func:`eval_runner.recorder.record_turn` persists for replay. The caller owns
    profile booting, because that determines the governed binding (ADR-0107).
    """
    os.environ.setdefault("HERMES_HOME", tempfile.mkdtemp(prefix="hermes-home-"))

    import run_agent

    original_openai = run_agent.OpenAI
    if openai_factory is not None:
        run_agent.OpenAI = openai_factory
    try:
        agent = run_agent.AIAgent(
            base_url=base_url,
            api_key=api_key,
            model=model,
            skip_context_files=True,
            skip_memory=True,
            quiet_mode=True,
            max_iterations=max_iterations,
        )
        agent._disable_streaming = True
        if governed_tool_names:
            # Admit the booted governed tools so the loop dispatches (not rejects)
            # the tool call. The schema list sent to the model is moot when the
            # provider is scripted — only the name allowlist matters there.
            agent.valid_tool_names = set(agent.valid_tool_names or set()) | set(
                governed_tool_names
            )
        result = agent.run_conversation(user_message, system_message=system_message)
    finally:
        run_agent.OpenAI = original_openai

    return {
        "final_response": result.get("final_response", "") or "",
        "messages": result.get("messages", []) or [],
    }


def run_scripted_agent(
    *,
    user_message: str,
    system_message: str | None = None,
    scripted_completions: Sequence[Mapping[str, Any]],
    governed_tool_names: Sequence[str] = (),
) -> dict[str, Any]:
    """Drive one real ``AIAgent`` turn against a scripted provider; capture the turn.

    The scripted ``OpenAI`` runs the loop with no model, network, or credentials.
    Returns ``{"final_response": str, "messages": list}`` for record/replay.
    """
    return run_agent_turn(
        user_message=user_message,
        system_message=system_message,
        base_url="http://eval.invalid/v1",
        api_key="sk-eval-fake",
        model="eval-fake-model",
        max_iterations=max(1, len(scripted_completions)),
        openai_factory=_scripted_openai_factory(scripted_completions),
        governed_tool_names=governed_tool_names,
    )


def run_live_turn(
    *,
    user_message: str,
    system_message: str | None = None,
    scripted_completions: Sequence[Mapping[str, Any]],
    profile: str | None = None,
) -> dict[str, Any]:
    """Run one real ``AIAgent`` turn against a scripted provider; capture the turn.

    When ``profile`` is set, the profile's governed ``toee_*`` tools are booted
    (unbound) and admitted so scripted tool calls dispatch through real governed
    execution. This is the eval recorder bridge; the bound async reply path is
    :func:`hermes_runtime.turn_runner.run_gateway_turn`.

    Returns ``{"final_response": str, "messages": list}`` — the exact shape
    :func:`eval_runner.recorder.record_turn` persists for replay.
    """
    governed_tool_names: list[str] = []
    if profile is not None:
        from hermes_runtime.boot import boot_profile

        governed_tool_names = boot_profile(profile).tool_names

    return run_scripted_agent(
        user_message=user_message,
        system_message=system_message,
        scripted_completions=scripted_completions,
        governed_tool_names=governed_tool_names,
    )
