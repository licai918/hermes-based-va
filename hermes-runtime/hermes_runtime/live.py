"""Bridge a real Nous ``hermes-agent`` turn into the record/replay harness.

A live turn is driven by a deterministic provider seam (scripted ChatCompletions)
so the eval harness captures ``{final_response, messages}`` from a *real*
``AIAgent`` loop with no model, network, or credentials, then hands it to
:func:`eval_runner.recorder.record_turn` for deterministic replay (ADR-0121,
ADR-0139). The provider is the only fake — the unavoidable nondeterministic
boundary; the agent loop and turn capture are real.

The agent is forced onto its non-streaming path (``_disable_streaming``): the
streaming path consumes ``create()`` as a chunk iterator, whereas the documented
non-streaming fallback returns a plain ``ChatCompletion`` we can script
deterministically. Tool execution wiring (the booted profile's gated driver) is a
later slice; this slice proves the capture/record/replay bridge with text turns.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Mapping, Sequence


def _chat_completion(content: str) -> Any:
    """A minimal OpenAI ``ChatCompletion`` carrying one assistant text reply."""
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


def _scripted_openai_factory(completions: Sequence[Mapping[str, Any]]) -> type:
    """An ``OpenAI``-shaped class whose ``chat.completions.create`` is scripted.

    The agent builds a fresh request client per call, so the scripted responses
    live in a queue closed over here (shared across every client instance) and are
    served in order. An exhausted queue raises rather than silently looping.
    """
    queue = [_chat_completion(str(c["content"])) for c in completions]

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


def run_live_turn(
    *,
    user_message: str,
    system_message: str | None = None,
    scripted_completions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Run one real ``AIAgent`` turn against a scripted provider; capture the turn.

    Returns ``{"final_response": str, "messages": list}`` — the exact shape
    :func:`eval_runner.recorder.record_turn` persists for replay.
    """
    os.environ.setdefault("HERMES_HOME", tempfile.mkdtemp(prefix="hermes-home-"))

    import run_agent

    original_openai = run_agent.OpenAI
    run_agent.OpenAI = _scripted_openai_factory(scripted_completions)
    try:
        agent = run_agent.AIAgent(
            base_url="http://eval.invalid/v1",
            api_key="sk-eval-fake",
            model="eval-fake-model",
            skip_context_files=True,
            skip_memory=True,
            quiet_mode=True,
            max_iterations=1,
        )
        agent._disable_streaming = True
        result = agent.run_conversation(user_message, system_message=system_message)
    finally:
        run_agent.OpenAI = original_openai

    return {
        "final_response": result.get("final_response", "") or "",
        "messages": result.get("messages", []) or [],
    }
