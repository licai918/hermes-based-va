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

The ``channel`` selects a per-channel system message (Slice 2): a short SMS reply,
an email body (with a subject alongside), or a staff-facing internal note. The
booted tool set is identical across channels, so the structural no-send invariant
holds for all three.

Slices 1–2 are scripted-only (Fork C1, mock-first ADR-0137): tests inject
completions via the existing :mod:`hermes_runtime.live` seam, and the keyless
default runs a deterministic local stub, so dev/CI draft without a model or key.
Real OpenRouter wiring is Slice 3.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional, Sequence

from toee_hermes.plugin.profiles import INTERNAL

from hermes_runtime.boot import boot_profile
from hermes_runtime.live import run_scripted_agent

# Reported as the provenance model when no real LLM produced the draft (scripted
# in tests, deterministic stub locally). Real model slugs arrive with Slice 3.
SCRIPTED_MODEL = "scripted"

# Per-channel system messages (ADR-0147 Slice 2). The channel selects how the same
# unbound internal_copilot turn is framed — short SMS reply, email body, or a
# staff-facing internal note. Each instructs "propose only, never send"; the agent
# has no send tool regardless (the structural no-send invariant, ADR-0035/0067).
_SYSTEM_MESSAGES = {
    "sms": (
        "You are a Toee Tire support copilot drafting a customer SMS reply for a "
        "staff member to review and send themselves. Write one short, plain, "
        "friendly message. Output only the suggested reply text; never send it."
    ),
    "email": (
        "You are a Toee Tire support copilot drafting a customer email reply for a "
        "staff member to review and send themselves. Write a clear, courteous email "
        "body with a greeting and sign-off. Output only the body text; never send it."
    ),
    "internal_note": (
        "You are a Toee Tire support copilot drafting an internal case note for "
        "staff — never shown to the customer. Summarize the situation and the "
        "suggested next step plainly for a colleague. Output only the note text."
    ),
}


def _system_message(channel: str) -> str:
    # The route validates channel against VALID_CHANNELS before run_turn is called,
    # so an unknown channel here is a programming error and should fail loudly.
    return _SYSTEM_MESSAGES[channel]


def _stub_subject(case_id: str) -> str:
    """A deterministic keyless email subject (Fork C1).

    ponytail: the subject is a fixed template, not model-generated — the scripted/
    keyless turn yields only a body. Ceiling: the subject ignores case content.
    Upgrade path: Slice 3's real provider derives the subject from the model output
    (e.g. a structured response or first-line convention) on this same seam.
    """
    return f"Re: your Toee Tire case {case_id}"


def _user_message(channel: str, case_id: str, prompt: Optional[str]) -> str:
    # case_id is an internal identifier, not customer PII; the agent gathers any
    # customer detail itself via its governed read tools (ADR-0147 decision 2).
    base = f"Draft a {channel} reply for case {case_id}."
    return f"{base} {prompt}".strip() if prompt else base


def _stub_draft(channel: str, case_id: str) -> str:
    """A deterministic keyless draft so the endpoint serves without a model/key."""
    return f"[draft:{channel}] Thanks for reaching out about case {case_id} - we're on it."


def make_copilot_run_turn(
    *, scripted_completions: Optional[Sequence[Mapping[str, Any]]] = None
) -> Callable[..., dict[str, Any]]:
    """Build the copilot draft ``run_turn``: an unbound ``internal_copilot`` turn.

    The returned ``run_turn(*, channel, case_id, prompt=None)`` boots
    ``internal_copilot`` unbound, runs a real ``AIAgent`` loop against the scripted
    provider seam, and returns ``{"draft", "model", "profile"}`` where ``draft`` is
    the captured ``final_response`` (Fork E1). ``scripted_completions`` injects the
    completion(s) in tests; absent, a deterministic keyless stub is used (Fork C1).
    """

    def run_turn(*, channel: str, case_id: str, prompt: Optional[str] = None) -> dict[str, Any]:
        # Unbound boot (no conversation_id): the Copilot path the boot docstring
        # calls out. This registers the internal_copilot read tools and — by
        # allowlist (ADR-0035) — NO send tool, so the turn is structurally no-send.
        booted = boot_profile(INTERNAL)
        completions = (
            scripted_completions
            if scripted_completions is not None
            else [{"content": _stub_draft(channel, case_id)}]
        )
        turn = run_scripted_agent(
            user_message=_user_message(channel, case_id, prompt),
            system_message=_system_message(channel),
            scripted_completions=completions,
            governed_tool_names=booted.tool_names,
        )
        result: dict[str, Any] = {
            "draft": turn["final_response"],
            "model": SCRIPTED_MODEL,
            "profile": INTERNAL,
        }
        # Email carries a subject (the in-process mock returns {channel, subject,
        # draft}); sms/internal_note do not. The endpoint shapes the per-channel
        # envelope from these fields.
        if channel == "email":
            result["subject"] = _stub_subject(case_id)
        return result

    return run_turn
