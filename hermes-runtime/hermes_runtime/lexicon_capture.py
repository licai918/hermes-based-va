"""The gateway-side L7 capture fork (0.0.5 S04, FR-4 / US4).

**A fork is not the agent.** ADR-0152 §5 says the external turn is READ-ONLY over
shared memory, and that stays true: the ``customer_service_external`` allowlist has
no ``toee_semantic_lexicon`` at all, so the agent that talks to the customer cannot
propose vocabulary and never could. What this module adds is *internal
infrastructure* that runs **after** that turn, on a different profile
(``internal_copilot``), on a different thread (the background worker), with a
toolset of exactly ONE action. The customer-facing agent's surface is unchanged.
That distinction is the ADR-0152 superseding note, and it is the reason this file
exists rather than a line in ``openrouter.py``.

The fork is the S23-0.0.3 copilot review pass ported to the external turn path,
with every one of its properties kept and one narrowed:

* **AFTER the reply, never in front of it.** ``openrouter.run_turn`` enqueues an
  ``l7_capture`` job (0.0.4 S04's structural answer to "the fork must never delay
  or fail the turn") and :func:`run_l7_capture_job` runs on the background worker.
  The enqueue itself is swallowed; the fork is not on the reply's thread at all.
* **Its OWN default-OFF flag** (``LEXICON_CAPTURE``). The eval record/replay path
  sets no flag *and* builds its turn without ``make_openrouter_run_turn``, so the
  determinism gate is pinned twice over (NFR-4).
* **Restricted toolset**: :data:`CAPTURE_FORK_TOOL_NAMES`, one action. It cannot
  reach L4, it cannot reach L6, it cannot reach the review inbox, and it cannot
  reach any DECIDE action -- a capture proposes, it never confirms (NFR-3).
* **Framework-derived capture** (S14-0.0.3): proposals come from the governed
  RESULT via ``lexicon_proposals_from_messages``, never from model prose, so a
  fork cannot narrate an entry into existence past the tool.

**What crosses which boundary, stated rather than assumed (NFR-6).** The captured
text is CUSTOMER-derived and L7 is a SHARED layer, so this arrow crosses the line
L4 is exempt from. Three things hold it: the fork is asked for *language*, never
facts about a person; the S01 write scan redacts PII in the ``evidence`` and
``proposer_context`` it stores (D2 -- redact, don't reject, because the evidence is
exactly what the admin needs in order to decide); and nothing is applied or
injected until a human confirms the row.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Optional, Sequence

from eval_runner.transcript import lexicon_proposals_from_messages
from toee_hermes.plugin.profiles import INTERNAL

from hermes_runtime.boot import boot_profile
from hermes_runtime.live import run_agent_turn, run_scripted_agent
from hermes_runtime.openrouter import (
    OpenRouterConfig,
    default_is_retryable,
    make_fallback_openai_factory,
    resolve_openrouter_config,
)
from hermes_runtime.tool_backend import _gateway_store, _lexicon_capture_extra_drivers

logger = logging.getLogger(__name__)

# The fork's ENTIRE governed surface. A tuple of explicit names rather than the L6
# fork's `startswith` prefix, because on this tool the prefix would be wrong: the
# other six `toee_semantic_lexicon__*` actions are the admin DECIDE surface, and a
# later slice that un-excludes one of them from `_AGENT_EXCLUDED_ACTIONS` would
# silently hand this fork the power to confirm its own proposals.
CAPTURE_FORK_TOOL_NAMES: tuple[str, ...] = ("toee_semantic_lexicon__propose_lexicon_entry",)

# D16: named from day one. How much of the conversation the fork reads back.
#
# ponytail: 8 turns -- four exchanges, enough to contain "do you mean X?" and the
# reply two turns later without paying for a whole session's history in every
# prompt. Raise it if real transcripts show confirmations landing further apart.
RECENT_EXCHANGE_LIMIT = 8

# Headroom for the reply iteration after the governed call (mirrors the L6 fork).
_DEFAULT_MAX_ITERATIONS = 12

# 1st line of defense (NFR-3/NFR-6), exactly as the L6 review prompt is: the fork
# is asked for LANGUAGE and explicitly refused anything about a person. The S01
# write scan is the 2nd line and the human confirm gate is the 3rd.
#
# "explicitly confirmed" is load-bearing and asserted by the tests: FR-4 captures a
# clarification the CUSTOMER agreed to, not one the agent guessed at. An unanswered
# "do you mean X?" is not a confirmation, and neither is the agent's own paraphrase.
_CAPTURE_SYSTEM_MESSAGE = (
    "You are a Toee Tire vocabulary reviewer reading a finished customer "
    "conversation. Your ONLY job is to record durable DOMAIN LANGUAGE the "
    "conversation confirmed: a surface form the customer used and the canonical "
    "form it means. Use the propose_lexicon_entry tool at most once, and ONLY when "
    "the agent explicitly asked the customer to confirm a meaning (\"do you mean "
    "X?\") and the customer answered affirmatively. If nothing was explicitly "
    "confirmed, record nothing -- an unanswered question, a guess, or your own "
    "paraphrase is not a confirmation. Never record facts about a person: no "
    "names, addresses, email addresses or phone numbers, and no preference about "
    "one customer. In proposer_context carry only identifiers and references such "
    "as a case id -- never contact details. You cannot contact the customer, "
    "cannot change the reply that was already sent, and cannot confirm your own "
    "proposal: an administrator decides."
)


def l7_capture_payload(context: Any) -> dict[str, Any]:
    """The ``l7_capture`` job payload -- identity keys only (ADR-0105 discipline).

    Deliberately NOT the transcript, unlike ``l6_review_payload``, which carries
    the copilot's draft. This one captures a CUSTOMER conversation, and the ``job``
    table has no retention story of its own yet (ADR-0153 fix #5), so copying the
    customer's words into it would create a second, unmanaged copy of them. The
    fork reads the exchange back from ``message_turn`` on the worker, where it
    already lives under the retention sweep's window.
    """
    return {
        "event_id": getattr(context, "event_id", None),
        "conversation_ref": getattr(context, "conversation_id", None),
        "sms_session_id": getattr(context, "sms_session_id", None),
    }


def format_exchange(rows: Sequence[Mapping[str, Any]]) -> str:
    """Render the recent turns as a two-speaker transcript for the fork's prompt.

    ``author`` is the ``message_turn`` column ('customer' | 'hermes'); anything
    that is not the customer is the agent, so an operator-sent turn reads as the
    business side rather than being dropped.
    """
    return "\n".join(
        f"{'Customer' if row.get('author') == 'customer' else 'Agent'}: "
        f"{(row.get('body') or '').strip()}"
        for row in rows
        if (row.get("body") or "").strip()
    )


def _recent_exchange(payload: Mapping[str, Any], store: Optional[Any]) -> str:
    """The conversation the fork reflects on, or ``""`` when there is none.

    Fail-open at every step (NFR-5, and this runs on a worker where raising just
    dead-letters a job for no benefit): no session ref, a store that cannot answer,
    or a read error all mean "nothing to capture from" rather than an exception.
    """
    session_id = payload.get("sms_session_id")
    if not session_id:
        return ""
    resolved_store = store if store is not None else _gateway_store()
    reader = getattr(resolved_store, "load_recent_exchange", None)
    if reader is None:
        return ""
    try:
        rows = reader(session_id, limit=RECENT_EXCHANGE_LIMIT)
    except Exception as exc:
        # ponytail: swallow to "no exchange" -- exception TYPE only, never
        # str(exc), which could echo back store-supplied customer content.
        logger.warning(
            "Lexicon capture exchange read failed error_type=%s; capturing nothing",
            type(exc).__name__,
        )
        return ""
    return format_exchange(rows or [])


def _capture_user_message(exchange: str) -> str:
    return (
        "Here is the conversation, oldest message first:\n\n"
        f"{exchange}\n\n"
        "Record one confirmed vocabulary mapping if the customer explicitly "
        "confirmed one, or nothing."
    )


def run_l7_capture_job(
    payload: Mapping[str, Any],
    *,
    capture_scripted_completions: Optional[Sequence[Mapping[str, Any]]] = None,
    store: Optional[Any] = None,
    config: Optional[OpenRouterConfig] = None,
    openai_factory: Any = None,
    is_retryable: Callable[[BaseException], bool] = default_is_retryable,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
) -> list[dict[str, Any]]:
    """The ``l7_capture`` job body: run ONE bounded fork; return its proposals.

    A SECOND agent pass booted ``internal_copilot`` -- structurally no-send, and
    here also structurally no-anything-else, because ``governed_tool_names`` is
    :data:`CAPTURE_FORK_TOOL_NAMES` alone. The ``_lexicon_capture_extra_drivers``
    overlay routes the write to Postgres when the capture flag is on (else the
    shared mock discards it). Provider precedence mirrors the L6 fork (scripted ->
    real OpenRouter -> keyless), and a keyless fork has no model to read with, so
    it captures nothing deterministically.

    Returns the framework-derived proposals as plain dicts. Nothing consumes the
    return value in production -- the governed call already wrote the row -- but a
    fork's routing decision is exactly what a test needs to be able to see.
    """
    exchange = _recent_exchange(payload, store)
    if not exchange:
        return []

    booted = boot_profile(INTERNAL, extra_drivers=_lexicon_capture_extra_drivers())
    tool_names = [name for name in booted.tool_names if name in CAPTURE_FORK_TOOL_NAMES]
    user_message = _capture_user_message(exchange)

    if capture_scripted_completions is not None:
        turn = run_scripted_agent(
            user_message=user_message,
            system_message=_CAPTURE_SYSTEM_MESSAGE,
            scripted_completions=capture_scripted_completions,
            governed_tool_names=tool_names,
            # EXCLUSIVE, or the restriction above is decoration: without it the
            # names are UNIONed into the agent's existing valid_tool_names, which
            # already holds the whole booted internal_copilot profile. See the
            # matching comment in copilot_turn._run_review_pass.
            tools_exclusive=True,
        )
    else:
        resolved = config
        if resolved is None and openai_factory is None:
            try:
                resolved = resolve_openrouter_config()
            except ValueError:
                resolved = None
        if resolved is None and openai_factory is None:
            # Keyless: no capture model available -> capture nothing.
            return []
        resolved = resolved or resolve_openrouter_config()
        base_factory = openai_factory
        if base_factory is None:
            from openai import OpenAI

            base_factory = OpenAI
        factory = make_fallback_openai_factory(
            base_factory=base_factory,
            fallback_model=resolved.fallback_model,
            is_retryable=is_retryable,
        )
        turn = run_agent_turn(
            user_message=user_message,
            system_message=_CAPTURE_SYSTEM_MESSAGE,
            base_url=resolved.base_url,
            api_key=resolved.api_key,
            model=resolved.model,
            max_iterations=max_iterations,
            openai_factory=factory,
            governed_tool_names=tool_names,
            tools_exclusive=True,  # see the scripted branch above
        )

    return [
        {
            "domain": p.domain,
            "entry_kind": p.entry_kind,
            "surface_form": p.surface_form,
            "canonical_form": p.canonical_form,
            "status": p.status,
        }
        for p in lexicon_proposals_from_messages(turn.get("messages", []) or [])
    ]
