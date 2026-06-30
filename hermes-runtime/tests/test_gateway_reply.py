"""Gateway reply derivation + delivery: capture turn -> customer-facing reply -> send.

The async job runs a bound governed turn (ADR-0107) and must deliver exactly one
customer-facing reply. :func:`outbound_reply_text` derives that reply from the
captured turn: the governed Textline send body when the agent sent one, else the
agent's ``final_response`` (ADR-0083). A send the turn-binding gate blocked is a
governed failure, so its (leaked) body is never delivered — the reply falls back.

:func:`make_gateway_turn_runner` composes the model-agnostic delivery path: run the
turn (the only model boundary, injected), derive the reply, send it via the same
``ReplySender`` the gateway uses for opt-out. Tests inject a fake run_turn so the
composition is verified with no agent boot.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from hermes_runtime.turn_runner import make_gateway_turn_runner, outbound_reply_text


def _send_turn(*, conversation_id: str, body: str, final_response: str) -> dict:
    return {
        "final_response": final_response,
        "messages": [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {
                            "name": "toee_textline_reply__send_message",
                            "arguments": json.dumps(
                                {"conversation_id": conversation_id, "body": body}
                            ),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "c1",
                "content": json.dumps(
                    {"message_id": "m1", "conversation_id": conversation_id, "body": body}
                ),
            },
        ],
    }


def _blocked_turn(*, leaked_body: str, final_response: str) -> dict:
    return {
        "final_response": final_response,
        "messages": [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {
                            "name": "toee_textline_reply__send_message",
                            "arguments": json.dumps(
                                {"conversation_id": "conv-OTHER", "body": leaked_body}
                            ),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "c1",
                "content": json.dumps(
                    {"error": "blocked by policy", "error_class": "policy_blocked"}
                ),
            },
        ],
    }


# --- G6a: outbound_reply_text ---------------------------------------------


def test_outbound_reply_text_uses_the_governed_textline_body() -> None:
    turn = _send_turn(
        conversation_id="conv-A", body="Out for delivery.", final_response="done"
    )
    assert outbound_reply_text(turn) == "Out for delivery."


def test_outbound_reply_text_falls_back_to_final_response_without_a_send() -> None:
    turn = {"final_response": "How can I help with your order?", "messages": []}
    assert outbound_reply_text(turn) == "How can I help with your order?"


def test_outbound_reply_text_falls_back_when_the_send_was_policy_blocked() -> None:
    turn = _blocked_turn(leaked_body="LEAK", final_response="Sorry, I could not do that.")

    text = outbound_reply_text(turn)

    assert "LEAK" not in text
    assert text == "Sorry, I could not do that."


# --- G6b: make_gateway_turn_runner ----------------------------------------


def test_gateway_turn_runner_sends_the_derived_reply_to_the_context_conversation() -> None:
    sent: list[tuple[str, str]] = []
    runner = make_gateway_turn_runner(
        reply_sender=lambda conv, text: sent.append((conv, text)),
        run_turn=lambda context, body: _send_turn(
            conversation_id=context.conversation_id, body="Shipped!", final_response="x"
        ),
    )

    runner(SimpleNamespace(conversation_id="conv-A"), "Where is my order?")

    assert sent == [("conv-A", "Shipped!")]


def test_gateway_turn_runner_delivers_fallback_not_the_blocked_body() -> None:
    sent: list[tuple[str, str]] = []
    runner = make_gateway_turn_runner(
        reply_sender=lambda conv, text: sent.append((conv, text)),
        run_turn=lambda context, body: _blocked_turn(
            leaked_body="LEAK", final_response="Sorry."
        ),
    )

    runner(SimpleNamespace(conversation_id="conv-A"), "Where is my order?")

    assert sent == [("conv-A", "Sorry.")]
    assert "LEAK" not in sent[0][1]


def test_gateway_turn_runner_invokes_on_reply_sent_after_delivery() -> None:
    mirrored: list[tuple[object, str]] = []
    runner = make_gateway_turn_runner(
        reply_sender=lambda conv, text: None,
        run_turn=lambda context, body: _send_turn(
            conversation_id=context.conversation_id, body="Shipped!", final_response="x"
        ),
        on_reply_sent=lambda ctx, text: mirrored.append((ctx, text)),
    )
    ctx = SimpleNamespace(conversation_id="conv-A")

    runner(ctx, "Where is my order?")

    assert mirrored == [(ctx, "Shipped!")]
