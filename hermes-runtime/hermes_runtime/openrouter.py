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

from toee_hermes.gateway.ingress import snapshot_as_identity_dict
from toee_hermes.gateway.normalize import normalize_e164
from toee_hermes.persona import EXTERNAL_CUSTOMER_SERVICE_PERSONA
from toee_hermes.plugin.hooks import render_injection
from toee_hermes.plugin.profiles import EXTERNAL

from hermes_runtime.boot import boot_profile
from hermes_runtime.live import run_agent_turn

# A non-tool-iterating turn still needs headroom for the reply iteration after a
# governed tool call; this caps a runaway loop without truncating a normal turn.
_DEFAULT_MAX_ITERATIONS = 12

# ADR-0009 pinned primary model for default conversation, tool planning, and
# customer-facing text. Overridable per environment via OPENROUTER_MODEL.
OPENROUTER_PRIMARY_MODEL = "deepseek/deepseek-v4-pro"

# ADR-0009 pinned fallback model: a retryable primary-model failure (rate limit,
# timeout, 5xx) retries the same completion against this. Overridable via env.
OPENROUTER_FALLBACK_MODEL = "qwen/qwen3.6-flash"

# OpenRouter's OpenAI-compatible endpoint; overridable for a proxy via env.
OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

_API_KEY_ENV = "OPENROUTER_API_KEY"
_BASE_URL_ENV = "OPENROUTER_BASE_URL"
_MODEL_ENV = "OPENROUTER_MODEL"
_FALLBACK_MODEL_ENV = "OPENROUTER_FALLBACK_MODEL"

# Transient OpenRouter/OpenAI failures worth retrying on the fallback model: a
# request that may succeed on a second provider. Auth/bad-request (4xx other than
# 408/409/429) are deterministic and never retried.
_RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})
_RETRYABLE_ERROR_NAMES = frozenset(
    {
        "RateLimitError",
        "APITimeoutError",
        "APIConnectionError",
        "InternalServerError",
        "APIError",
    }
)


def _with_channel_identity(
    identity: Optional[dict[str, Any]], from_phone: str
) -> dict[str, Any]:
    """Merge the SMS channel identity (E.164) into the turn's identity dict (S01).

    Runs at the turn boundary rather than in ``snapshot_as_identity_dict``: the
    phone lives on ``AgentTurnContext``, not the Session Identity Snapshot. Always
    returns a dict — even for an unmatched caller with no snapshot — so Customer
    Memory binding (S02) has ingress-controlled channel identity to key off,
    never a model-supplied tool param (RK-3).
    """
    merged = dict(identity) if identity else {}
    merged["channel"] = "sms"
    merged["channel_identity"] = normalize_e164(from_phone)
    return merged


@dataclass(frozen=True)
class OpenRouterConfig:
    """Resolved OpenRouter connection for one agent turn (ADR-0009)."""

    base_url: str
    api_key: str
    model: str
    fallback_model: str = OPENROUTER_FALLBACK_MODEL


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
    fallback_model = (
        os.environ.get(_FALLBACK_MODEL_ENV) or ""
    ).strip() or OPENROUTER_FALLBACK_MODEL
    return OpenRouterConfig(
        base_url=base_url,
        api_key=api_key,
        model=model,
        fallback_model=fallback_model,
    )


def default_is_retryable(exc: BaseException) -> bool:
    """Whether an OpenRouter completion error should retry on the fallback model.

    Retries transient failures (rate limit, timeout, connection, 5xx) by HTTP
    status when the SDK exposes one, else by the OpenAI SDK exception class name —
    so it works without constructing real SDK errors and stays resilient to SDK
    version drift. Deterministic 4xx (auth, bad request) are not retried.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status in _RETRYABLE_STATUS
    return type(exc).__name__ in _RETRYABLE_ERROR_NAMES


def make_fallback_openai_factory(
    *,
    base_factory: Any,
    fallback_model: str,
    is_retryable: Callable[[BaseException], bool] = default_is_retryable,
) -> Any:
    """Wrap an OpenAI client factory with per-completion fallback (ADR-0009).

    The agent issues every chat completion against the primary model; when a call
    raises a retryable error (``is_retryable``), the *same* call is retried once
    against ``fallback_model``. Non-retryable errors propagate unchanged. Retrying
    per-completion (not per-turn) means the fallback never repeats a governed action
    already taken earlier in the turn. Unknown attributes delegate to the wrapped
    client so the agent sees an ordinary OpenAI client.
    """

    class _FallbackCompletions:
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def create(self, **kwargs: Any) -> Any:
            try:
                return self._inner.create(**kwargs)
            except Exception as exc:
                if not is_retryable(exc):
                    raise
                return self._inner.create(**{**kwargs, "model": fallback_model})

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    class _FallbackChat:
        def __init__(self, inner: Any) -> None:
            self._inner = inner
            self.completions = _FallbackCompletions(inner.completions)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    class _FallbackClient:
        def __init__(self, inner: Any) -> None:
            self._inner = inner
            self.chat = _FallbackChat(inner.chat)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    def factory(*args: Any, **kwargs: Any) -> Any:
        return _FallbackClient(base_factory(*args, **kwargs))

    return factory


def make_openrouter_run_turn(
    *,
    system_message: Optional[str] = None,
    config: Optional[OpenRouterConfig] = None,
    openai_factory: Any = None,
    is_retryable: Callable[[BaseException], bool] = default_is_retryable,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
    tools_exclusive: bool = True,
) -> Callable[[Any, str], Mapping[str, Any]]:
    """Build the production ``run_turn``: a conversation-bound governed turn over OpenRouter.

    The returned ``(context, inbound_body)`` callable boots the External profile
    bound to ``context.conversation_id`` (ADR-0107) and runs a real ``AIAgent`` loop
    against OpenRouter, returning the captured ``{final_response, messages}`` turn for
    :func:`hermes_runtime.turn_runner.make_gateway_turn_runner` to derive + deliver
    the reply. The provider is wrapped with per-completion fallback to the config's
    secondary model (ADR-0009). ``config`` defaults to :func:`resolve_openrouter_config`
    (resolved per turn so a credential rotation is picked up); ``openai_factory``
    injects a deterministic provider in tests (the real OpenAI client is used
    otherwise).
    """

    def run_turn(context: Any, inbound_body: str) -> Mapping[str, Any]:
        resolved = config or resolve_openrouter_config()
        base_factory = openai_factory
        if base_factory is None:
            from openai import OpenAI

            base_factory = OpenAI
        factory = make_fallback_openai_factory(
            base_factory=base_factory,
            fallback_model=resolved.fallback_model,
            is_retryable=is_retryable,
        )
        snapshot = getattr(context, "session_identity_snapshot", None)
        base_identity = (
            snapshot_as_identity_dict(snapshot) if snapshot is not None else None
        )
        # S01: enrich with the caller's channel identity (E.164) here, where
        # AgentTurnContext.from_phone is in scope — the snapshot alone never has it.
        identity = _with_channel_identity(base_identity, context.from_phone)
        # ponytail: boot_profile registers pre_llm_call on a local PluginManager, but
        # AIAgent invokes hooks on the global singleton (discover_plugins → register).
        # Prepend the snapshot here so the model sees verified identity (ADR-0140).
        injected = render_injection(identity, None)
        user_message = f"{injected}\n\n{inbound_body}" if injected else inbound_body
        booted = boot_profile(
            EXTERNAL,
            conversation_id=context.conversation_id,
            sms_session_id=getattr(context, "sms_session_id", None),
            identity=identity,
        )
        return run_agent_turn(
            user_message=user_message,
            system_message=system_message or EXTERNAL_CUSTOMER_SERVICE_PERSONA,
            base_url=resolved.base_url,
            api_key=resolved.api_key,
            model=resolved.model,
            max_iterations=max_iterations,
            openai_factory=factory,
            governed_tool_names=booted.tool_names,
            tools_exclusive=tools_exclusive,
        )

    return run_turn
