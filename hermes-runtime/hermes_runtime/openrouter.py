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

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from toee_hermes.drivers.mock.memory import binding_key_from_identity
from toee_hermes.gateway.ingress import snapshot_as_identity_dict
from toee_hermes.gateway.normalize import (
    TEXTLINE_SMS,
    canonicalize_email,
    is_email_channel,
    normalize_e164,
)
from toee_hermes.persona import EXTERNAL_CUSTOMER_SERVICE_PERSONA
from toee_hermes.plugin.hooks import render_injection
from toee_hermes.plugin.profiles import EXTERNAL

from hermes_runtime.boot import boot_profile
from hermes_runtime.live import run_agent_turn
from hermes_runtime.tool_backend import (
    _gateway_store,
    _turn_extra_drivers,
    memory_enabled,
)

logger = logging.getLogger(__name__)

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
    identity: Optional[dict[str, Any]], from_identity: str, channel: str = TEXTLINE_SMS
) -> dict[str, Any]:
    """Merge the ingress channel identity into the turn's identity dict (S01/S17).

    Runs at the turn boundary rather than in ``snapshot_as_identity_dict``: the
    channel identity lives on ``AgentTurnContext``, not the Session Identity
    Snapshot. Always returns a dict — even for an unmatched caller with no snapshot —
    so Customer Memory binding (S02) has ingress-controlled channel identity to key
    off, never a model-supplied tool param (RK-3).

    S17 (⚠️ binding correctness): the channel MUST reflect the real ingress channel.
    An email turn binds ``channel="email"`` with the canonicalized From address; an
    SMS turn binds ``channel="sms"`` with the E.164 phone. Hardcoding ``"sms"`` here
    would compute the WRONG binding key for an email turn and silently read/write
    another binding's memory — a governance/privacy bug.
    """
    merged = dict(identity) if identity else {}
    if is_email_channel(channel):
        merged["channel"] = "email"
        merged["channel_identity"] = canonicalize_email(from_identity)
    else:
        merged["channel"] = "sms"
        merged["channel_identity"] = normalize_e164(from_identity)
    return merged


def _load_turn_memory(
    identity: dict[str, Any], store: Optional[Any]
) -> Optional[list[dict[str, Any]]]:
    """Load this turn's Customer Memory preference slots for injection (S07, FR-1).

    Gated by :func:`memory_enabled` (S05) — the same single source of truth as the
    write overlay (S04): a mock/unset deployment reads nothing and the turn still
    completes (FR-7/RK-6). The binding key comes from the ingress-controlled
    ``identity`` via :func:`binding_key_from_identity` — the SAME core the write
    path uses, so the read key is byte-identical to the stored key (R2 round-trip).

    Read fail-closed: no resolvable binding injects nothing (never raises — unlike
    the write tool's ``policy_blocked``). A datastore read error also degrades to
    nothing, because memory is never a hard dependency of answering (FR-7).
    """
    if not memory_enabled():
        return None
    resolved = binding_key_from_identity(identity)
    if resolved is None:
        return None
    binding_key, _kind = resolved
    resolved_store = store if store is not None else _gateway_store()
    try:
        return resolved_store.load_customer_memory(binding_key)
    except Exception as exc:
        # ponytail: swallow to None so a DB hiccup degrades to "no memory injected",
        # never a failed reply (FR-7 / the hooks module's provider-error philosophy).
        # S11: WARN so the swallow isn't silent. binding_key + exception TYPE only —
        # never str(exc)/traceback, which could echo back store-supplied content.
        logger.warning(
            "Customer Memory read failed binding_key=%s error_type=%s; "
            "turn continues with no memory injected",
            binding_key,
            type(exc).__name__,
        )
        return None


def _provisional_key_for(identity: dict[str, Any]) -> Optional[str]:
    """This caller's provisional binding key from the SAME channel-identity fields.

    A verified identity short-circuits :func:`binding_key_from_identity` to its
    Shopify id, so to find the caller's PRE-verification provisional slots we derive
    the provisional key from the channel fields alone (S01 always threads them on).
    Byte-identical to the key the write path stored under while unverified (R2)."""
    resolved = binding_key_from_identity(
        {
            "channel": identity.get("channel"),
            "channel_identity": identity.get("channel_identity"),
        }
    )
    return resolved[0] if resolved is not None else None


def _linked_provisional_keys(
    identity: dict[str, Any], verified_key: str, store: Any
) -> list[str]:
    """Every linked channel's provisional key to merge onto ``verified_key`` (S19/
    FR-19, ADR-0151).

    Deterministic precedence: THIS turn's own channel first (the freshest,
    just-stated signal), then every other channel identity linked to the same
    verified customer via ``identity_link``, in a fixed ``(channel,
    channel_identity)`` order. Because :meth:`PostgresGatewayStore.
    merge_provisional_memory`'s ``ON CONFLICT ... DO NOTHING`` lets the FIRST
    writer of an empty verified slot win, this list's order IS the precedence
    for a slot stated on more than one linked channel. Deduped, so a channel
    that is both "this turn's own" and separately linked merges exactly once.

    ``list_channel_identities_for_customer`` is an optional store capability
    (only :class:`PostgresGatewayStore` implements it) -- a test double that
    lacks it degrades to the single-channel (pre-S19) behavior rather than
    raising.
    """
    keys: list[str] = []
    own_key = _provisional_key_for(identity)
    if own_key is not None:
        keys.append(own_key)
    list_linked = getattr(store, "list_channel_identities_for_customer", None)
    if list_linked is not None:
        for channel, channel_identity in list_linked(verified_key):
            resolved = binding_key_from_identity(
                {"channel": channel, "channel_identity": channel_identity}
            )
            if resolved is not None and resolved[0] not in keys:
                keys.append(resolved[0])
    return keys


def _merge_provisional_memory(identity: dict[str, Any], store: Optional[Any]) -> bool:
    """Merge pre-verification provisional slots onto the verified record, from
    EVERY linked channel (S10/FR-4, generalized cross-channel in S19/FR-19).

    Runs on the async turn — never ``process_inbound`` / the webhook ack (RK-5) — on
    every verified ingress, so it also covers a manually-seeded identity link, not
    only the first-ever verification. Gated by :func:`memory_enabled` and fail-closed
    exactly like the read: a disabled backend, a non-verified/ambiguous identity, or
    no resolvable source keys degrades to "no merge" and the turn still replies
    (FR-7). A per-key merge failure leaves that channel's provisional rows intact to
    retry on the next verified turn (each merge is independently idempotent), and
    does not prevent the OTHER linked channels from merging this turn.

    Returns whether a merge actually fired this turn (S11 observability): ``True``
    when the store reports it moved/overrode at least one provisional slot for at
    least one source key; ``False`` on every skip, no-op, or swallowed error.
    """
    if not memory_enabled():
        return False
    verified = binding_key_from_identity(identity)
    # Only a verified single-customer resolution merges: an ambiguous or unmatched
    # identity resolves to kind "provisional" (or None) and is skipped (ADR-0112).
    if verified is None or verified[1] != "verified":
        return False
    resolved_store = store if store is not None else _gateway_store()
    provisional_keys = _linked_provisional_keys(identity, verified[0], resolved_store)
    if not provisional_keys:
        return False
    merge_fired = False
    for provisional_key in provisional_keys:
        try:
            merged = resolved_store.merge_provisional_memory(provisional_key, verified[0])
        except Exception as exc:
            # ponytail: swallow so a merge hiccup never fails the reply; the provisional
            # rows survive and the next verified turn retries (FR-7, same philosophy as
            # the read). Continue to the next linked channel -- one bad source must not
            # block the others (S19).
            # S11: WARN so the swallow isn't silent. Binding keys + exception TYPE only.
            logger.warning(
                "Customer Memory merge failed provisional_key=%s verified_key=%s "
                "error_type=%s; provisional slots left intact for retry",
                provisional_key,
                verified[0],
                type(exc).__name__,
            )
            continue
        if merged is not None:
            merge_fired = True
    return merge_fired


def _log_turn_memory(
    identity: dict[str, Any],
    memory: Optional[list[dict[str, Any]]],
    merge_fired: bool,
) -> None:
    """Emit the compact per-turn Customer Memory observability line (S11, PRD §6.4).

    So a real conversation can be audited after the fact ("did this customer get
    THEIR memory?") without ever logging PII: records the resolved binding_key (an
    identifier, not customer content), the injected slot NAMES only — never slot
    values, which are customer-authored free text and the FR-6 persistent-injection
    surface — and whether the S10 provisional->verified merge fired this turn.
    Re-derives the binding key independently of :func:`_load_turn_memory` (cheap and
    pure) so this note still fires when memory is disabled or the read itself failed.
    """
    resolved = binding_key_from_identity(identity)
    binding_key = resolved[0] if resolved is not None else None
    slot_names = [
        slot.get("slot") for slot in (memory or []) if slot.get("slot") is not None
    ]
    logger.info(
        "Customer Memory turn: binding_key=%s slots=%s merge_fired=%s",
        binding_key,
        slot_names,
        merge_fired,
    )


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
    store: Optional[Any] = None,
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
    otherwise). ``store`` injects the gateway store for the turn-time Customer Memory
    read (S07); when ``None`` a DSN-based :class:`PostgresGatewayStore` is built per
    turn, but only under :func:`memory_enabled` (mock/unset deployments never touch
    Postgres).
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
        # S01/S17: enrich with the caller's channel identity here, where
        # AgentTurnContext.from_phone (+ .channel) is in scope — the snapshot alone
        # never has it. The channel drives email-vs-SMS binding (RK-4 correctness).
        identity = _with_channel_identity(
            base_identity,
            context.from_phone,
            getattr(context, "channel", TEXTLINE_SMS),
        )
        # S10/FR-4: on a verified ingress, merge the caller's pre-verification
        # provisional slots onto the verified record BEFORE the read below, so the
        # just-merged preferences are injected on this same turn (PAC-3). No-op /
        # fail-closed when not verified or memory is disabled.
        merge_fired = _merge_provisional_memory(identity, store)
        # ponytail: boot_profile registers pre_llm_call on a local PluginManager, but
        # AIAgent invokes hooks on the global singleton (discover_plugins → register).
        # Prepend the snapshot + Customer Memory here so the model sees verified
        # identity and prior preferences (ADR-0140, S07/FR-1). The memory read is
        # gated + fail-closed in _load_turn_memory (nothing injected when disabled,
        # unbound, or the store errors).
        memory = _load_turn_memory(identity, store)
        _log_turn_memory(identity, memory, merge_fired)
        injected = render_injection(identity, memory)
        user_message = f"{injected}\n\n{inbound_body}" if injected else inbound_body
        booted = boot_profile(
            EXTERNAL,
            conversation_id=context.conversation_id,
            sms_session_id=getattr(context, "sms_session_id", None),
            identity=identity,
            # S10: merges the Customer Memory overlay (S04) with the Knowledge
            # overlay (S09/FR-5) -- one dict, each gated on its own independent
            # axis (see _turn_extra_drivers).
            extra_drivers=_turn_extra_drivers(),
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
