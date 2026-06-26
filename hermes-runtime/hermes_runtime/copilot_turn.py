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

Slice 1 is scripted-only (Fork C1, mock-first ADR-0137): tests inject completions
via the existing :mod:`hermes_runtime.live` seam, and the keyless default runs a
deterministic local stub, so dev/CI draft without a model or key. Real OpenRouter
wiring is Slice 3.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional, Sequence

from toee_hermes.plugin.profiles import INTERNAL

from hermes_runtime.boot import boot_profile
from hermes_runtime.live import run_scripted_agent

# Reported as the provenance model when no real LLM produced the draft (scripted
# in tests, deterministic stub locally). Real model slugs arrive with Slice 3.
SCRIPTED_MODEL = "scripted"

# One short, plain, staff-reviewed SMS reply. The agent never sends; it proposes.
# ponytail: Slice 1 wires SMS only — ADR-0147 Slice 2 adds the email (subject+body)
# and internal-note (staff-facing) system messages on this same seam.
_SMS_SYSTEM_MESSAGE = (
    "You are a Toee Tire support copilot drafting a customer SMS reply for a staff "
    "member to review and send themselves. Write one short, plain, friendly message. "
    "Output only the suggested reply text; never send it yourself."
)


def _system_message(channel: str) -> str:
    return _SMS_SYSTEM_MESSAGE


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
        return {
            "draft": turn["final_response"],
            "model": SCRIPTED_MODEL,
            "profile": INTERNAL,
        }

    return run_turn
