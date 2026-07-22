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
from hermes_runtime.outbound_send import (
    InMemoryOutboundSendLog,
    OutboundMirrorFailed,
    deliver_once,
)

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

# ponytail: hard cap on an SMS reply's length -- roughly three concatenated
# segments (a segment is 160 GSM-7 chars, 153 when concatenated), not one.
# Upgrade path is MMS/segment-aware send. The number is a product decision.
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
    outbound_log: Optional[Any] = None,
) -> Callable[[Any, str, Optional[str]], None]:
    """Compose the model-agnostic async reply path into a gateway ``TurnRunner``.

    The returned ``(context, inbound_body, job_id)`` callable runs the bound governed
    turn (``run_turn`` — the injected model boundary), derives the customer-facing
    reply, and delivers it. The route has already reloaded + verified the binding
    (ADR-0106/0107) before this runs.

    **This function holds S03's single outbound wrap (FR-12).** Delivery is one
    closure — the ``reply_sender`` call *and* the ``on_reply_sent`` mirror — handed
    to :func:`~hermes_runtime.outbound_send.deliver_once`, so a retried or replayed
    turn skips the whole thing rather than re-texting the customer or writing a
    second ``message_turn`` row. All three outbound surfaces the slice names ride
    this one wrap because all three are reached from these two lines: the real
    SimpleTexting POST and the ``REPLY_SENDER=simulated`` no-op are both *which*
    ``reply_sender`` was injected (``gateway_composition.resolve_reply_sender``),
    and the S17 email reply mirror is ``on_reply_sent``. Adding a per-sender guard
    instead would have made a fourth outbound path easy to add unguarded.

    ``job_id`` is the queue's job id, threaded from ``turn_worker.run_once``; it is
    ``None`` on the ADR-0106 parity route, which delivers with no job behind it.
    ``outbound_log`` defaults to an in-memory record so a DB-free ``create_app()``
    runs the *same* wrap — there is no unguarded branch.
    """
    log = outbound_log if outbound_log is not None else InMemoryOutboundSendLog()

    def turn_runner(
        context: Any, inbound_body: str, job_id: Optional[str] = None
    ) -> None:
        turn = run_turn(context, inbound_body)
        reply = outbound_reply_text(turn)
        channel = getattr(context, "channel", SIMPLETEXTING_SMS)
        # S17: SMS is clipped; an email reply is not 480-char-clipped.
        mirror_is_the_reply = is_email_channel(channel)
        if not mirror_is_the_reply:
            reply = clip_sms_reply(reply)

        def deliver() -> None:
            # reply_sender is the SMS provider client, and it strips its argument
            # to digits. There is no email provider (RK-4), so routing an email
            # turn through it would POST a real SMS to whatever number the inbound
            # payload's conversation_id happened to contain -- caller-chosen,
            # billed to us (ADR-0153). On email the mirror below IS the delivery,
            # which is why it still sits inside this one wrap.
            if not mirror_is_the_reply:
                reply_sender(context.conversation_id, reply)
            if on_reply_sent is None:
                return
            try:
                on_reply_sent(context, reply)
            except Exception as exc:
                # Two actions, one record (fix wave 1, finding 4). Past this line
                # the provider already took the message on SMS, so a mirror
                # failure must NOT be recorded as a failed send -- the customer
                # has the reply, and the retry must never re-text. It is still
                # raised: the missing Workbench row dead-letters the job so a
                # human fixes the thread rather than the record quietly lying.
                if mirror_is_the_reply:
                    raise  # on email the mirror IS the delivery: a real send failure
                raise OutboundMirrorFailed(
                    f"reply delivered but the message_turn mirror failed: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc

        deliver_once(
            log=log,
            job_id=job_id,
            event_id=context.event_id,
            conversation_id=context.conversation_id,
            channel=channel,
            deliver=deliver,
        )

    return turn_runner
