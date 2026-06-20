"""Production gateway turn runner: a governed, conversation-bound async reply turn.

The internal agent-turn job (ADR-0106/0107) reloads the inbound turn's context,
verifies the binding, then runs the customer-facing agent. :func:`run_gateway_turn`
is that run: it boots the External profile *bound* to the turn's ``conversation_id``
(:func:`hermes_runtime.boot.boot_profile`) so every governed dispatch carries the
binding and the turn-binding gate constrains ``toee_textline_reply.send_message`` to
that conversation alone (ADR-0066). A scripted provider seam keeps the run
deterministic for tests; the agent loop, governed dispatch, and capture are real.

The reply is delivered from the captured turn by the gateway (the agent's governed
Textline send, else its ``final_response``), so this returns the captured turn —
``{final_response, messages}`` — the same shape the recorder/replay layer consumes.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from toee_hermes.plugin.profiles import EXTERNAL

from hermes_runtime.boot import boot_profile
from hermes_runtime.live import run_scripted_agent


def run_gateway_turn(
    *,
    conversation_id: str,
    inbound_body: str,
    scripted_completions: Sequence[Mapping[str, Any]],
    sms_session_id: Optional[str] = None,
    system_message: Optional[str] = None,
    profile: str = EXTERNAL,
) -> dict[str, Any]:
    """Run one governed External turn bound to ``conversation_id`` (ADR-0107).

    Returns the captured ``{"final_response": str, "messages": list}`` turn.
    """
    booted = boot_profile(
        profile, conversation_id=conversation_id, sms_session_id=sms_session_id
    )
    return run_scripted_agent(
        user_message=inbound_body,
        system_message=system_message,
        scripted_completions=scripted_completions,
        governed_tool_names=booted.tool_names,
    )
