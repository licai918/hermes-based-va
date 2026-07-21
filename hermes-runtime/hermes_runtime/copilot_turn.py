"""Copilot draft provider: an unbound ``internal_copilot`` agent turn (ADR-0147).

The drafts half of the agent-turn capability ADR-0141 named. Unlike
:func:`hermes_runtime.openrouter.make_openrouter_run_turn` (External, bound to a
conversation, ending in a customer send), a copilot draft turn boots
``internal_copilot`` **UNBOUND** (no ``conversation_id``) and ends in *proposed
text, never a send*: the agent's ``final_response`` IS the draft (Fork E1),
mirroring how the External reply derives from ``final_response``.

No-auto-send is **structural**: ``internal_copilot``'s allowlist (ADR-0035) has no
send tool, so the booted turn cannot send to a customer (ADR-0067) — there is no
runtime guard to forget. The agent still holds the copilot *read* tools
(``toee_workbench_read``, ``toee_knowledge_search``, …) to ground the draft.

The ``channel`` selects a per-channel system message: a short SMS reply, an email
body (with a subject alongside), a staff-facing internal note (Slice 2), or a
conversational ``chat`` reply (Slice 4, #39 — the staff-facing copilot conversation,
not a customer draft). The booted tool set is identical across all of them, so the
structural no-send invariant holds for chat exactly as for the draft channels.

Customer Memory is propose-only on this turn (0.0.3 S13/FR-14, ADR-0150 --
reverses 0.0.2's S20 autonomous persist): the agent still keeps
``toee_customer_memory`` in its allowlist and can call ``upsert_preference``,
but the write never reaches the datastore (see ``_turn_extra_drivers`` below).
Its inert call is extracted into a structured ``proposals[]`` on the result
(0.0.3 S14/FR-15, :func:`eval_runner.transcript.memory_proposals_from_messages`)
so a rep can later Accept it -- surfacing only, no new write path.

Provider seam (Fork C1, mock-first ADR-0137), in precedence order:

1. ``scripted_completions`` injected (tests/eval) -> the deterministic
   :mod:`hermes_runtime.live` scripted seam: a real ``AIAgent`` loop with no
   model, network, or key.
2. ``OPENROUTER_API_KEY`` present (or an explicit ``config``/``openai_factory``)
   -> the real OpenRouter boundary (ADR-0009: deepseek primary / qwen fallback),
   reusing :mod:`hermes_runtime.openrouter`'s config + per-completion fallback
   verbatim — no new provider abstraction, the External precedent unbound.
3. Otherwise -> a deterministic keyless stub completion, so local dev and CI draft
   without a model or key, exactly as the dispatch server runs against MockDriver.

``OPENROUTER_API_KEY`` is read only via :func:`resolve_openrouter_config` and is
never logged.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Optional, Sequence

from eval_runner.transcript import (
    experience_proposals_from_messages,
    memory_proposals_from_messages,
)
from toee_hermes.drivers.mock.memory import binding_key_from_identity
from toee_hermes.plugin.hooks import render_injection
from toee_hermes.plugin.profiles import INTERNAL

from hermes_runtime.boot import boot_profile
from hermes_runtime.job_queue import L6_REVIEW_JOB_TYPE, PostgresJobQueue
from hermes_runtime.live import run_agent_turn, run_scripted_agent
from hermes_runtime.openrouter import (
    OpenRouterConfig,
    default_is_retryable,
    make_fallback_openai_factory,
    resolve_openrouter_config,
)
from hermes_runtime.tool_backend import (
    _agent_experience_extra_drivers,
    _gateway_store,
    _turn_extra_drivers,
    agent_experience_enabled,
    agent_experience_injection_enabled,
    load_confirmed_experience,
    memory_enabled,
    record_memory_injection_metric,
)

logger = logging.getLogger(__name__)

# Reported as the provenance model when no real LLM produced the draft (scripted
# in tests, deterministic stub locally). A real keyed turn reports the resolved
# OpenRouter model slug instead (ADR-0009).
SCRIPTED_MODEL = "scripted"

# Headroom for the reply iteration after a governed context-read tool call; caps a
# runaway loop without truncating a normal draft turn (mirrors openrouter.py).
_DEFAULT_MAX_ITERATIONS = 12

# An email turn frames the subject on a leading ``Subject:`` line (see the email
# system message); the derivation peels it off so the body is the draft text.
_SUBJECT_LINE_PREFIX = "subject:"

# Per-channel system messages (ADR-0147 Slice 2 drafts; Slice 4 adds `chat`). The
# channel selects how the same unbound internal_copilot turn is framed — short SMS
# reply, email body, staff-facing internal note, or (Slice 4) a conversational chat
# reply that helps the staff member work the case. Each instructs "propose only,
# never send"; the agent has no send tool regardless (the structural no-send
# invariant, ADR-0035/0067). Every channel also gets the _MEMORY_WRITE_DISCIPLINE
# suffix appended below (S03, FR-1): the draft agent keeps toee_customer_memory
# under the SAME internal_copilot allowlist for all four channels (propose-only
# since S13/ADR-0150 -- the call never persists, see _turn_extra_drivers above),
# so the no-inferred guard has to cover every one of them regardless.
_SYSTEM_MESSAGES = {
    "sms": (
        "You are a Toee Tire support copilot drafting a customer SMS reply for a "
        "staff member to review and send themselves. Write one short, plain, "
        "friendly message. Output only the suggested reply text; never send it."
    ),
    "email": (
        "You are a Toee Tire support copilot drafting a customer email reply for a "
        "staff member to review and send themselves. Put the subject on the first "
        "line as 'Subject: <subject>', then a clear, courteous email body with a "
        "greeting and sign-off. Output only the subject line and body; never send it."
    ),
    "internal_note": (
        "You are a Toee Tire support copilot drafting an internal case note for "
        "staff — never shown to the customer. Summarize the situation and the "
        "suggested next step plainly for a colleague. Output only the note text."
    ),
    # Slice 4 (#39): /api/copilot/chat. A conversational copilot turn — the reply is
    # the agent's final_response (relabeled `reply` by the endpoint), not a per-channel
    # draft. If the staff member asks for a customer reply the agent provides the
    # suggested text for them to review/edit/send; it can never send (no send tool).
    "chat": (
        "You are a Toee Tire support copilot helping a staff member work a customer "
        "support case. Answer their question about the case concisely and helpfully. "
        "If they ask you to draft a customer reply, provide the suggested reply text "
        "for them to review, edit, and send themselves. Never send anything yourself."
    ),
}
# S03 (FR-1): mirrors persona.py:99-103's proven external rule ("ONLY when the
# customer explicitly asks... NEVER save a preference you merely inferred"), adapted
# to the case-scoped draft turn. Appended to every channel in one place — rather than
# pasted into all four literals above — so the guard cannot drift out of sync between
# channels; the draft agent keeps upsert_preference (guarded, not removed).
_MEMORY_WRITE_DISCIPLINE = (
    "Only use toee_customer_memory to save a preference when the customer has "
    "explicitly stated a durable preference in this case's conversation — never "
    "one merely inferred from tone, history, or a single order."
)
# Tool-parameter conventions (fix for the copilot draft path, task_8525be3c).
# build_tool_schema (hermes/toee_hermes/plugin/schemas.py) gives every governed tool
# an OPEN schema ("properties": {}), so the model gets ZERO parameter-name guidance
# from the schema — the only place conventions live is the system prompt. The
# External persona (persona.py:68-94) documents them; these Copilot draft prompts did
# not, so the draft agent guessed `order_id` for get_order, and because governed
# dispatch sanitizes a wrong-param failure to a generic "temporarily unavailable"
# (execute.py TOOL_UNAVAILABLE_MESSAGE) the agent could not self-correct — it just
# concluded systems were down. Mirror the read-tool conventions here.
# KEEP IN SYNC with persona.py:68-94.
_TOOL_PARAM_CONVENTIONS = (
    "When you read case data, use the EXACT tool parameter names — a wrong name is "
    "treated as a missing value and the lookup fails: toee_shopify_read get_order "
    '{order_number} (the bare order number, e.g. "1042"), list_customer_orders {}, '
    "get_product {sku|product_id}, search_products {query}; toee_easyroutes_read get_delivery_status "
    "{order_number}; toee_qbo_read is allowed ONLY for a verified customer whose "
    "email link is confirmed, so you MUST call toee_identity_lookup "
    "get_email_link_status {shopify_customer_id} FIRST and only call get_invoice "
    "{invoice_number} or get_ar_summary {customer_id} if the returned status is linked."
)
# Grounded-chunks discipline (S10, FR-5): mirrors persona.py's toee_knowledge_search
# bullet -- in-turn content is the retrieved chunks, never synthesis, and an empty
# result is an honest miss, never a guess.
_KNOWLEDGE_GROUNDING = (
    "When you use toee_knowledge_search, answer only from the returned results and "
    "cite the source page title; if the results are empty, say plainly that you "
    "don't have that on hand rather than guessing."
)
_SYSTEM_MESSAGES = {
    channel: (
        f"{message} {_TOOL_PARAM_CONVENTIONS} {_MEMORY_WRITE_DISCIPLINE} "
        f"{_KNOWLEDGE_GROUNDING}"
    )
    for channel, message in _SYSTEM_MESSAGES.items()
}


def _system_message(channel: str) -> str:
    # The route validates channel against VALID_CHANNELS before run_turn is called,
    # so an unknown channel here is a programming error and should fail loudly.
    return _SYSTEM_MESSAGES[channel]


def _derive_email_subject_and_body(final_response: str, case_id: str) -> tuple[str, str]:
    """Split an email turn's ``final_response`` into ``(subject, body)`` (Fork C1).

    The email system message asks the model to lead with a ``Subject: <subject>``
    line; when the first non-blank line follows that convention, that line is peeled
    off the body — so the body the staff member edits never carries a stray
    ``Subject:`` line — and its text becomes the subject. An EMPTY subject (a bare
    ``Subject:`` line, or a model that left it blank) still strips that line from the
    body but uses the deterministic case-scoped fallback subject (M2: previously the
    bare ``Subject:`` line leaked into the body). When the first real line is not a
    ``Subject:`` line at all (the keyless stub, or a model that skipped the
    convention), fall back to the same subject and keep the whole response as the
    body. Body handling is symmetric across both paths (``.strip()``), so
    ``{channel, subject, draft}`` always holds and the scripted/stub path stays
    deterministic for tests.
    """
    text = final_response or ""
    fallback_subject = f"Re: your Toee Tire case {case_id}"
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue  # skip leading blank lines to the first real line
        stripped = line.strip()
        if stripped.lower().startswith(_SUBJECT_LINE_PREFIX):
            subject = stripped[len(_SUBJECT_LINE_PREFIX) :].strip()
            body = "\n".join(lines[index + 1 :]).strip()
            # Peel the Subject: line off the body either way; an empty subject uses
            # the deterministic fallback so the bare line never survives in the draft.
            return (subject or fallback_subject), body
        break  # first real line is not a Subject: line -> fall back, keep whole body
    return fallback_subject, text.strip()


def _user_message(channel: str, case_id: str, prompt: Optional[str]) -> str:
    # case_id is an internal identifier, not customer PII; the agent gathers any
    # customer detail itself via its governed read tools (ADR-0147 decision 2).
    if channel == "chat":
        # Chat is single-shot (the in-memory handleChat contract): the prompt IS the
        # staff member's message about the case — conversational, not "draft a reply".
        base = f"A staff member is working case {case_id} and asks:"
        return f"{base} {prompt}".strip() if prompt else f"Help the staff member with case {case_id}."
    base = f"Draft a {channel} reply for case {case_id}."
    return f"{base} {prompt}".strip() if prompt else base


def _stub_draft(channel: str, case_id: str) -> str:
    """A deterministic keyless draft so the endpoint serves without a model/key."""
    if channel == "chat":
        return f"Looking at case {case_id} now - how can I help with it?"
    return f"[draft:{channel}] Thanks for reaching out about case {case_id} - we're on it."


def _load_case_memory(
    case_id: str, store: Optional[Any]
) -> tuple[Optional[dict[str, Any]], Optional[list[dict[str, Any]]]]:
    """Resolve the case's thread identity and its Customer Memory slots (S08, FR-1).

    The Copilot draft seam is bound to a ``case_id``, not a phone (S07's external
    seam), so the binding key is derived from the case's ``customer_thread``: the
    store resolves the thread's Shopify id (verified) or channel identity
    (provisional) into an identity dict of the same shape S02/S07 use, and
    :func:`binding_key_from_identity` — the SAME shared core the write path uses —
    turns it into the byte-identical read key (R2 round-trip).

    The case IDENTITY is resolved independent of :func:`memory_enabled`
    (task_86123a78): business-tool reads (get_order etc.) verify against
    ``ToolExecutionContext.identity``, so a verified case must resolve even when
    Customer Memory is disabled. Only the memory-SLOTS load is gated by
    ``memory_enabled`` (S05), fail-closed like the external read (S07): disabled, an
    unknown/threadless case, no resolvable binding, no slots, or a datastore error all
    inject nothing and never raise — memory is never a hard dependency of drafting
    (FR-7). The identity is returned even when there are no slots so the turn's
    ToolExecutionContext binds both business reads and an employee-confirmed
    correction write to the right key.
    """
    # Resolve the case's thread identity FIRST, decoupled from memory_enabled()
    # (task_86123a78): business-tool reads (get_order, get_delivery_status, QBO)
    # verify against ToolExecutionContext.identity, so a verified case must resolve
    # its identity even when Customer Memory slots are disabled -- the mock-backed
    # eval recording forces TOOL_BACKEND=mock, and without this the draft agent could
    # never read a verified customer's own order/delivery/AR data. Only the memory
    # SLOTS load below stays gated by memory_enabled(). A provided store is always
    # usable; without one we dial the gateway store ONLY when memory is enabled, so a
    # genuinely no-datastore turn never reaches for a datastore that isn't there
    # (S05/FR-7).
    resolved_store = store if store is not None else (
        _gateway_store() if memory_enabled() else None
    )
    if resolved_store is None:
        return None, None
    try:
        identity = resolved_store.load_case_identity(case_id)
    except Exception as exc:
        # ponytail: swallow to None so a lookup hiccup degrades to "no memory
        # injected", never a failed draft (FR-7) -- same philosophy as the read
        # swallow below. S10/S11 parity: WARN so the swallow isn't silent. No
        # binding_key exists yet (identity never resolved), so log case_id (an
        # internal id, not PII -- see _user_message above) + exception TYPE only --
        # never str(exc)/traceback, which could echo back store-supplied content.
        logger.warning(
            "Customer Memory identity lookup failed case_id=%s error_type=%s; "
            "turn continues with no memory injected",
            case_id,
            type(exc).__name__,
        )
        return None, None
    if identity is None:
        return None, None
    if not memory_enabled():
        # Identity stands (business-tool reads + write-binding); no memory slots when
        # Customer Memory is disabled -- FR-7 degradation is memory-only, not identity.
        return identity, None
    resolved = binding_key_from_identity(identity)
    if resolved is None:
        return identity, None
    binding_key, _kind = resolved
    try:
        return identity, resolved_store.load_customer_memory(binding_key)
    except Exception as exc:
        # ponytail: swallow to None so a DB hiccup degrades to "no memory injected",
        # never a failed draft (FR-7) — but keep identity for the write-binding.
        # S11 parity (openrouter.py _load_turn_memory): WARN so the swallow isn't
        # silent. binding_key + exception TYPE only -- never str(exc)/traceback,
        # which could echo back store-supplied content.
        logger.warning(
            "Customer Memory read failed binding_key=%s error_type=%s; "
            "turn continues with no memory injected",
            binding_key,
            type(exc).__name__,
        )
        return identity, None


# --- S23 (FR-22, NFR-3): the post-copilot-turn learning-loop review pass -------
# THE 1st line of defense (NFR-3): the review fork is asked for OPERATIONAL
# learnings only and is EXPLICITLY forbidden person-specific data. The S22
# write-side scan is the 2nd line (rejects PII/injection before the INSERT); the
# S24 human confirm gate is the 3rd (a proposed row is inert until confirmed).
# "person-specific" is load-bearing and asserted by the tests.
_REVIEW_SYSTEM_MESSAGE = (
    "You are a Toee Tire support quality reviewer reflecting on a support turn a "
    "copilot just drafted. Your ONLY job is to record durable OPERATIONAL learnings "
    "for the team -- procedures, conventions, tool quirks, or recurring patterns "
    "that would help handle similar cases better next time. Use the "
    "propose_experience tool to record at most one such learning; if the turn "
    "surfaced nothing durable, record nothing. NEVER record person-specific data or "
    "customer PII of any kind: no names, order numbers, email addresses, phone "
    "numbers, addresses, or any fact about a specific customer. A learning must be "
    "a general operational rule, never a note about one person. You cannot contact "
    "the customer and cannot change the draft; you only record learnings."
)


def _review_user_message(case_id: str, draft_result: Mapping[str, Any]) -> str:
    """Frame the just-completed turn for the review fork (transcript + case id).

    Minimal case context only (``case_id`` is an internal id, not PII -- see
    ``_user_message``); the draft text is what the copilot produced, which the
    reviewer generalizes from. The prompt forbids copying any person-specific
    detail the draft happens to contain into a proposal.
    """
    draft = draft_result.get("draft") or ""
    actions = [
        m.get("name")
        for m in (draft_result.get("messages") or [])
        if isinstance(m, dict) and m.get("role") == "tool" and m.get("name")
    ]
    tools_line = f"Tools the copilot used: {', '.join(actions)}." if actions else "The copilot used no tools."
    return (
        f"Review the copilot turn for case {case_id}. {tools_line}\n\n"
        f"The copilot's draft was:\n{draft}\n\n"
        "Record one durable operational learning if there is one, or nothing."
    )


def l6_review_payload(case_id: str, draft_result: Mapping[str, Any]) -> dict[str, Any]:
    """The ``l6_review`` job payload (0.0.4 S04, FR-11).

    The review prompt is built HERE, at the end of the copilot turn, from exactly
    the data the inline fork used to read (``case_id`` + the draft + the tool names
    in the transcript) -- so the fork sees a byte-identical prompt whether it runs
    inline or on the queue. Nothing else from the turn crosses: the full governed
    transcript stays out of the ``job`` table.
    """
    return {
        "case_id": case_id,
        "review_prompt": _review_user_message(case_id, draft_result),
    }


def run_l6_review_job(
    payload: Mapping[str, Any],
    *,
    review_scripted_completions: Optional[Sequence[Mapping[str, Any]]] = None,
    config: Optional[OpenRouterConfig] = None,
    openai_factory: Any = None,
    is_retryable: Callable[[BaseException], bool] = default_is_retryable,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
) -> list[dict[str, Any]]:
    """The ``l6_review`` job body: run the fork for a payload the queue handed back.

    Same fork, same prompt, same governed toolset as the inline S23 pass -- only
    the caller moved (S04). ``review_scripted_completions`` is the deterministic
    test/eval seam the copilot turn used to own; the background worker never
    passes it.
    """
    return _run_review_pass(
        user_message=payload["review_prompt"],
        review_scripted_completions=review_scripted_completions,
        config=config,
        openai_factory=openai_factory,
        is_retryable=is_retryable,
        max_iterations=max_iterations,
    )


def _run_review_pass(
    *,
    user_message: str,
    review_scripted_completions: Optional[Sequence[Mapping[str, Any]]],
    config: Optional[OpenRouterConfig],
    openai_factory: Any,
    is_retryable: Callable[[BaseException], bool],
    max_iterations: int,
) -> list[dict[str, Any]]:
    """Run ONE bounded review fork over the just-completed turn; return proposals.

    A SECOND agent pass booted ``internal_copilot`` (structurally no-send) whose
    governed toolset is RESTRICTED to ``toee_agent_experience`` only -- it is not
    drafting a customer reply, only reflecting. The ``_agent_experience_extra_drivers``
    overlay routes ``propose_experience`` to Postgres when the L6 flag is on
    (else the shared mock discards it). Provider precedence mirrors the draft
    (scripted -> real OpenRouter -> keyless), but a keyless fork has no model to
    reflect with, so it proposes nothing deterministically. Proposals are captured
    framework-derived from the governed RESULT (:func:`experience_proposals_from_messages`),
    never model free-text.
    """
    booted = boot_profile(INTERNAL, extra_drivers=_agent_experience_extra_drivers())
    # Restricted toolset: only the L6 propose tool, never the reply/read tools.
    tool_names = [n for n in booted.tool_names if n.startswith("toee_agent_experience__")]

    if review_scripted_completions is not None:
        turn = run_scripted_agent(
            user_message=user_message,
            system_message=_REVIEW_SYSTEM_MESSAGE,
            scripted_completions=review_scripted_completions,
            governed_tool_names=tool_names,
        )
    else:
        resolved = config
        if resolved is None and openai_factory is None:
            try:
                resolved = resolve_openrouter_config()
            except ValueError:
                resolved = None
        if resolved is None and openai_factory is None:
            # Keyless: no review model available -> propose nothing (deterministic).
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
            system_message=_REVIEW_SYSTEM_MESSAGE,
            base_url=resolved.base_url,
            api_key=resolved.api_key,
            model=resolved.model,
            max_iterations=max_iterations,
            openai_factory=factory,
            governed_tool_names=tool_names,
        )

    return [
        {"kind": p.kind, "content": p.content, "status": p.status}
        for p in experience_proposals_from_messages(turn.get("messages", []) or [])
    ]


def make_copilot_run_turn(
    *,
    scripted_completions: Optional[Sequence[Mapping[str, Any]]] = None,
    config: Optional[OpenRouterConfig] = None,
    openai_factory: Any = None,
    is_retryable: Callable[[BaseException], bool] = default_is_retryable,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
    store: Optional[Any] = None,
    queue: Optional[Any] = None,
) -> Callable[..., dict[str, Any]]:
    """Build the copilot draft ``run_turn``: an unbound ``internal_copilot`` turn.

    The returned ``run_turn(*, channel, case_id, prompt=None)`` boots
    ``internal_copilot`` unbound, runs a real ``AIAgent`` loop against the resolved
    provider, and returns ``{"draft", "model", "profile", "messages", "proposals"}``
    (email also carries ``subject``) where ``draft`` is the captured
    ``final_response`` (Fork E1), ``messages`` is the governed tool-call transcript
    (S07, FR-3/R4) -- the shape :func:`eval_runner.transcript.turn_result_from_
    transcript` parses -- and ``proposals`` is the structured, framework-derived
    Customer Memory proposal list extracted from it (S14, FR-15).

    The bounded post-turn learning-loop review fork (S23, FR-22) no longer runs on
    this thread: with the ``AGENT_EXPERIENCE_LEARNING`` L6 flag on, ``run_turn``
    ENQUEUES an ``l6_review`` job and the background worker runs it (0.0.4 S04,
    FR-11). The flag is still DEFAULT OFF, so the eval record/replay path enqueues
    nothing and the result is byte-identical to the draft-only shape. ``queue``
    injects the :class:`~hermes_runtime.job_queue.PostgresJobQueue` (tests); the
    default constructs one lazily, only when the flag is on.

    Provider precedence (Fork C1): ``scripted_completions`` (tests) → real
    OpenRouter when ``OPENROUTER_API_KEY`` is set or ``config``/``openai_factory``
    is injected (ADR-0009, per-completion fallback) → a deterministic keyless stub.
    Building never requires a key; tests inject scripted completions, so CI is
    keyless. The key is read only by :func:`resolve_openrouter_config`, never logged.
    """

    def run_turn(*, channel: str, case_id: str, prompt: Optional[str] = None) -> dict[str, Any]:
        # S08/FR-1: resolve the case's thread identity + its Customer Memory slots
        # (gated + fail-closed in _load_case_memory). Boot bound to that identity so
        # an employee-confirmed correction write binds from context, and prepend the
        # memory block so the draft is grounded in prior preferences.
        identity, memory = _load_case_memory(case_id, store)
        # S26 (FR-28): memory-injection counter emit, same gate/rationale as the
        # external turn (openrouter.py) -- turn-safe, gated on memory_enabled().
        record_memory_injection_metric(bool(memory))
        # Unbound boot (no conversation_id): the Copilot path the boot docstring
        # calls out. This registers the internal_copilot read tools and — by
        # allowlist (ADR-0035) — NO send tool, so the turn is structurally no-send.
        # extra_drivers (S10; S13/FR-14 reverses S20 -- ADR-0150): merges the
        # Knowledge overlay (S09/FR-5, routes toee_knowledge_search to the
        # retriever) with the Customer Memory overlay EXCLUDED
        # (include_memory_write=False) -- toee_customer_memory stays on the
        # shared mock driver regardless of memory_enabled(), so an
        # agent-initiated write from this unbound draft turn is never
        # persisted; the draft can only propose (S14 builds the proposal
        # envelope). Memory READ-injection (identity/slots, right above) is
        # unaffected -- it goes through the gateway store directly, never this
        # overlay. See tool_backend._turn_extra_drivers.
        booted = boot_profile(
            INTERNAL,
            identity=identity,
            extra_drivers=_turn_extra_drivers(include_memory_write=False),
        )
        system_message = _system_message(channel)
        base_user_message = _user_message(channel, case_id, prompt)
        # S25 (FR-25): confirmed L6 learnings for the draft, gated on the COPILOT
        # injection flag (its OWN axis, default OFF -- the eval record/replay path
        # sets neither flag, so nothing is read/injected there and the gate stays
        # deterministic, NFR-6). Read is bounded + fail-closed (returns None on any
        # error, NFR-5); only status='confirmed' rows ever come back.
        experience = (
            load_confirmed_experience(store)
            if agent_experience_injection_enabled()
            else None
        )
        # Memory + confirmed learnings — the case identity is not surfaced as a
        # snapshot block (the agent gathers case detail via its governed read tools,
        # ADR-0147 decision 2). render_injection returns None when everything is
        # empty, so no binding / no slots / no learnings / disabled injects nothing.
        injected = render_injection(None, memory, experience)
        user_message = (
            f"{injected}\n\n{base_user_message}" if injected else base_user_message
        )

        if scripted_completions is not None:
            # Tests/eval: a real AIAgent loop with no model, network, or key.
            turn = run_scripted_agent(
                user_message=user_message,
                system_message=system_message,
                scripted_completions=scripted_completions,
                governed_tool_names=booted.tool_names,
            )
            model = SCRIPTED_MODEL
        else:
            resolved = config
            if resolved is None and openai_factory is None:
                # No injected provider: route through real OpenRouter only when a
                # key is configured (ADR-0009); a missing key falls through to the
                # keyless stub below (resolve_openrouter_config fails closed).
                try:
                    resolved = resolve_openrouter_config()
                except ValueError:
                    resolved = None
            if resolved is None and openai_factory is None:
                # Keyless: a deterministic local stub completion through the same
                # real loop, so the endpoint serves without a model or key.
                turn = run_scripted_agent(
                    user_message=user_message,
                    system_message=system_message,
                    scripted_completions=[{"content": _stub_draft(channel, case_id)}],
                    governed_tool_names=booted.tool_names,
                )
                model = SCRIPTED_MODEL
            else:
                # Real OpenRouter (or an injected provider): wrap the client with
                # per-completion fallback to the secondary model (ADR-0009), mirroring
                # the External production turn — but booted internal_copilot UNBOUND.
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
                    system_message=system_message,
                    base_url=resolved.base_url,
                    api_key=resolved.api_key,
                    model=resolved.model,
                    max_iterations=max_iterations,
                    openai_factory=factory,
                    governed_tool_names=booted.tool_names,
                )
                model = resolved.model

        draft = turn["final_response"]
        result: dict[str, Any] = {"draft": draft, "model": model, "profile": INTERNAL}
        # S07 (FR-3/R4): thread the governed tool-call transcript through so an eval
        # scenario's mechanical no-inferred-write assertion (forbid_inferred_upsert)
        # can inspect it -- previously computed as `turn` but silently dropped here
        # (S05 spike finding 5). Purely additive: agent_turn_app.py, the only
        # production consumer of this result, reads draft/subject/model/profile only.
        result["messages"] = list(turn.get("messages", []) or [])
        # S14 (FR-15): the propose-only toee_customer_memory call (S13/ADR-0150) is
        # extracted into a structured proposals[] here -- framework-derived from the
        # governed tool-call RESULT (see memory_proposals_from_messages), never
        # model free-text. Nothing persists; this is pure extraction from the same
        # transcript above. Empty when the agent made no memory tool calls.
        result["proposals"] = [
            {"slot": p.slot, "value": p.value, "evidence_turn": p.evidence_turn}
            for p in memory_proposals_from_messages(result["messages"])
        ]
        # Email carries a subject (the in-process mock returns {channel, subject,
        # draft}); the subject is derived from the turn's final_response, and the
        # body becomes the draft. sms/internal_note key only on draft.
        if channel == "email":
            subject, body = _derive_email_subject_and_body(draft, case_id)
            result["subject"] = subject
            result["draft"] = body

        # S23 (FR-22) / 0.0.4 S04 (FR-11): the bounded post-turn review fork. The
        # rep's draft is ALREADY produced (result above); the fork runs AFTER it
        # and can never delay or fail it -- which S04 makes STRUCTURAL rather than
        # a comment, by enqueuing an `l6_review` job instead of running the fork on
        # this thread. The background worker runs it (run_l6_review_job).
        # Gate unchanged: the L6 flag, DEFAULT OFF, so the eval record/replay path
        # still enqueues nothing and stays byte-identical (determinism).
        # Any exception is caught, logged, and swallowed (turn resilience RK).
        if agent_experience_enabled():
            try:
                resolved_queue = queue if queue is not None else PostgresJobQueue()
                resolved_queue.enqueue(
                    l6_review_payload(case_id, result),
                    job_type=L6_REVIEW_JOB_TYPE,
                    # ponytail: ONE attempt, matching the pre-S04 semantics exactly
                    # -- an inline fork that raised was swallowed and never retried.
                    # The fork WRITES (propose_experience), so a retry could land a
                    # second proposed row for one turn; a failure dead-letters
                    # instead, which S05 surfaces. Raise it the day the fork is
                    # made idempotent.
                    max_attempts=1,
                )
            except Exception as exc:
                # ponytail: swallow so the learning loop can never fail the copilot
                # turn (RK). case_id is an internal id (not PII); log the exception
                # TYPE only, never str(exc), which could echo store-supplied content.
                logger.warning(
                    "Agent-experience review enqueue failed case_id=%s error_type=%s; "
                    "the copilot turn is unaffected",
                    case_id,
                    type(exc).__name__,
                )
        return result

    return run_turn
