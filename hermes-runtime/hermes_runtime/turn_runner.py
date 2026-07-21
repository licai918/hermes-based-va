"""Production gateway turn runner: a governed, conversation-bound async reply turn.

The internal agent-turn job (ADR-0106/0107) reloads the inbound turn's context,
verifies the binding, then runs the customer-facing agent. :func:`run_gateway_turn`
is that run: it boots the External profile *bound* to the turn's ``conversation_id``
(:func:`hermes_runtime.boot.boot_profile`) so every governed dispatch carries the
binding and the turn-binding gate constrains ``toee_sms_reply.send_message`` to
that conversation alone (ADR-0066). A scripted provider seam keeps the run
deterministic for tests; the agent loop, governed dispatch, and capture are real.

The reply is delivered from the captured turn by the gateway (the agent's governed
SMS send, else its ``final_response``), so this returns the captured turn —
``{final_response, messages}`` — the same shape the recorder/replay layer consumes.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional, Sequence

from eval_runner.transcript import turn_result_from_transcript
from toee_hermes.gateway.normalize import SIMPLETEXTING_SMS, is_email_channel
from toee_hermes.plugin.profiles import EXTERNAL

from hermes_runtime.boot import boot_profile
from hermes_runtime.live import run_scripted_agent

# Runs one bound governed turn for a reloaded context + its inbound body and returns
# the captured ``{final_response, messages}`` turn. This is the only model boundary:
# tests inject a scripted run; production injects the real OpenRouter-backed run.
RunTurn = Callable[[Any, str], Mapping[str, Any]]

# The gateway's outbound reply sender (conversation_id, text) — the same seam used
# for the opt-out confirmation (gateway_app.ReplySender).
ReplySender = Callable[[str, str], None]

# Optional hook after a reply is delivered (context, reply text) — mirrors to the
# durable store for Workbench Case Thread Context when wired (ADR-0082/0140).
OnReplySent = Callable[[Any, str], None]

# ponytail: hard cap for one SMS segment; upgrade path is MMS/segment-aware send.
_SMS_MAX_CHARS = 480


def clip_sms_reply(body: str, *, max_chars: int = _SMS_MAX_CHARS) -> str:
    """Trim an agent reply to SMS-friendly length before SMS delivery."""
    text = body.strip()
    if len(text) <= max_chars:
        return text
    clipped = text[: max_chars - 1].rsplit(" ", 1)[0] or text[: max_chars - 1]
    return clipped.rstrip(".,;:! ") + "…"


def run_gateway_turn(
    *,
    conversation_id: str,
    inbound_body: str,
    scripted_completions: Sequence[Mapping[str, Any]],
    sms_session_id: Optional[str] = None,
    system_message: Optional[str] = None,
    profile: str = EXTERNAL,
    extra_drivers: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Run one governed External turn bound to ``conversation_id`` (ADR-0107).

    ``extra_drivers`` threads the per-tool driver overlay (S04/S09/S10) into this
    boot, same reasoning as :func:`hermes_runtime.live.run_live_turn` -- a bare
    boot after an overlay boot silently clobbers it back to mock in the shared
    upstream ``tools.registry`` singleton.

    Returns the captured ``{"final_response": str, "messages": list}`` turn.
    """
    booted = boot_profile(
        profile,
        conversation_id=conversation_id,
        sms_session_id=sms_session_id,
        extra_drivers=extra_drivers,
    )
    return run_scripted_agent(
        user_message=inbound_body,
        system_message=system_message,
        scripted_completions=scripted_completions,
        governed_tool_names=booted.tool_names,
    )


def outbound_reply_text(turn: Mapping[str, Any]) -> str:
    """Derive the one customer-facing reply from a captured turn (ADR-0083).

    The reply is the governed SMS send body when the agent sent one, else the
    agent's ``final_response``. A send the turn-binding gate blocked is a governed
    failure (``error_class``), so its body is not customer-facing text — the reply
    falls back rather than delivering the rejected content.
    """
    result = turn_result_from_transcript(
        final_response=turn.get("final_response", "") or "",
        messages=list(turn.get("messages", []) or []),
    )
    return result.outbound_text


def make_gateway_turn_runner(
    *,
    reply_sender: ReplySender,
    run_turn: RunTurn,
    on_reply_sent: Optional[OnReplySent] = None,
) -> Callable[[Any, str], None]:
    """Compose the model-agnostic async reply path into a gateway ``TurnRunner``.

    The returned ``(context, inbound_body)`` callable runs the bound governed turn
    (``run_turn`` — the injected model boundary), derives the customer-facing reply,
    and sends it to the context's conversation via ``reply_sender``. The route has
    already reloaded + verified the binding (ADR-0106/0107) before this runs.
    """

    def turn_runner(context: Any, inbound_body: str) -> None:
        turn = run_turn(context, inbound_body)
        reply = outbound_reply_text(turn)
        is_email = is_email_channel(getattr(context, "channel", SIMPLETEXTING_SMS))
        # S17: SMS is clipped to one segment; an email reply is not 480-char-clipped.
        if not is_email:
            reply = clip_sms_reply(reply)
        # reply_sender is the SMS provider client, and it strips its argument to
        # digits. There is no email provider (RK-4), so routing an email turn
        # through it would POST a real SMS to whatever number the inbound payload's
        # conversation_id happened to contain — caller-chosen, billed to us
        # (ADR-0153). The email reply is delivered by the mirror below, which is
        # what the simulator reads back.
        if not is_email:
            reply_sender(context.conversation_id, reply)
        if on_reply_sent is not None:
            on_reply_sent(context, reply)

    return turn_runner
