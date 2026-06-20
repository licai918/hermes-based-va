"""OpenRouter-backed provider for the production async turn (ADR-0009, ADR-0139).

The gateway turn runner's only model boundary is ``run_turn``. In production it
routes chat completions through OpenRouter with the ADR-0009 pinned primary model
``deepseek/deepseek-v4-pro`` (fallback ``qwen/qwen3.6-flash`` on retryable
errors is a separate routing concern, not wired here yet). The agent talks to
OpenRouter over the OpenAI-compatible API, so only the base URL, API key, and
model slug differ from the eval seam.

:func:`resolve_openrouter_config` reads the connection from the environment,
defaulting the base URL and primary model so a minimally-configured deployment is
correct by construction, and failing closed when the API key is absent (a missing
key is a deploy misconfiguration, never a silent fall-through to an unauthed call).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from toee_hermes.plugin.profiles import EXTERNAL

from hermes_runtime.boot import boot_profile
from hermes_runtime.live import run_agent_turn

# A non-tool-iterating turn still needs headroom for the reply iteration after a
# governed tool call; this caps a runaway loop without truncating a normal turn.
_DEFAULT_MAX_ITERATIONS = 12

# ADR-0009 pinned primary model for default conversation, tool planning, and
# customer-facing text. Overridable per environment via OPENROUTER_MODEL.
OPENROUTER_PRIMARY_MODEL = "deepseek/deepseek-v4-pro"

# OpenRouter's OpenAI-compatible endpoint; overridable for a proxy via env.
OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

_API_KEY_ENV = "OPENROUTER_API_KEY"
_BASE_URL_ENV = "OPENROUTER_BASE_URL"
_MODEL_ENV = "OPENROUTER_MODEL"


@dataclass(frozen=True)
class OpenRouterConfig:
    """Resolved OpenRouter connection for one agent turn."""

    base_url: str
    api_key: str
    model: str


def resolve_openrouter_config() -> OpenRouterConfig:
    """Resolve the OpenRouter connection from the environment (fail-closed).

    Raises ``ValueError`` when ``OPENROUTER_API_KEY`` is missing or blank.
    """
    api_key = (os.environ.get(_API_KEY_ENV) or "").strip()
    if not api_key:
        raise ValueError(
            f"{_API_KEY_ENV} is required to route the agent turn through OpenRouter "
            "(ADR-0009); set it in the environment."
        )
    base_url = (os.environ.get(_BASE_URL_ENV) or "").strip() or OPENROUTER_DEFAULT_BASE_URL
    model = (os.environ.get(_MODEL_ENV) or "").strip() or OPENROUTER_PRIMARY_MODEL
    return OpenRouterConfig(base_url=base_url, api_key=api_key, model=model)


def make_openrouter_run_turn(
    *,
    system_message: Optional[str] = None,
    config: Optional[OpenRouterConfig] = None,
    openai_factory: Any = None,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
) -> Callable[[Any, str], Mapping[str, Any]]:
    """Build the production ``run_turn``: a conversation-bound governed turn over OpenRouter.

    The returned ``(context, inbound_body)`` callable boots the External profile
    bound to ``context.conversation_id`` (ADR-0107) and runs a real ``AIAgent`` loop
    against OpenRouter, returning the captured ``{final_response, messages}`` turn for
    :func:`hermes_runtime.turn_runner.make_gateway_turn_runner` to derive + deliver
    the reply. ``config`` defaults to :func:`resolve_openrouter_config` (resolved per
    turn so a credential rotation is picked up); ``openai_factory`` injects a
    deterministic provider in tests (the real OpenAI client is used otherwise).
    """

    def run_turn(context: Any, inbound_body: str) -> Mapping[str, Any]:
        resolved = config or resolve_openrouter_config()
        booted = boot_profile(
            EXTERNAL,
            conversation_id=context.conversation_id,
            sms_session_id=getattr(context, "sms_session_id", None),
        )
        return run_agent_turn(
            user_message=inbound_body,
            system_message=system_message,
            base_url=resolved.base_url,
            api_key=resolved.api_key,
            model=resolved.model,
            max_iterations=max_iterations,
            openai_factory=openai_factory,
            governed_tool_names=booted.tool_names,
        )

    return run_turn
