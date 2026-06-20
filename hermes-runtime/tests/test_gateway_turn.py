"""Gateway turn runner: a bound async Textline turn enforces ADR-0107 in the real loop.

:func:`hermes_runtime.turn_runner.run_gateway_turn` boots the External profile bound
to the inbound turn's ``conversation_id`` (``register_turn``) and runs a real
``AIAgent`` turn against a scripted provider. The turn-binding gate (ADR-0107/0066)
then admits a governed ``toee_textline_reply.send_message`` only when it targets the
bound conversation; a send aimed at any other conversation is a governed
``policy_blocked`` failure, so the leaked body never becomes customer-facing text.

Capture round-trips through record/replay (ADR-0121, ADR-0139); the LLM provider is
the only fake — the agent loop, governed dispatch, and turn capture are all real.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from eval_runner.fixtures import load_scenario
from eval_runner.recorder import record_turn
from eval_runner.replay import ReplayAgentHarness

from hermes_runtime.turn_runner import run_gateway_turn

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


def _replay(turn: dict):
    scenario = load_scenario("text_first_launch", "01", EVAL_DIR)
    with tempfile.TemporaryDirectory(prefix="gw-turn-") as tmp:
        root = Path(tmp)
        record_turn(turn=turn, scenario=scenario, transcripts_dir=root)
        return ReplayAgentHarness(root).run_turn(scenario)


def test_gateway_turn_admits_a_reply_bound_to_the_inbound_conversation() -> None:
    body = "Your order TOEE-1001 shipped today - tracking to follow."

    turn = run_gateway_turn(
        conversation_id="conv-A",
        inbound_body="Where is my order?",
        system_message="You are Toee Tire support.",
        scripted_completions=[
            {
                "tool_calls": [
                    {
                        "name": "toee_textline_reply__send_message",
                        "arguments": {"conversation_id": "conv-A", "body": body},
                    }
                ]
            },
            {"content": "Done - I've texted you the shipping update."},
        ],
    )

    result = _replay(turn)

    assert [(c.tool, c.action) for c in result.tool_calls] == [
        ("toee_textline_reply", "send_message")
    ]
    assert result.tool_calls[0].ok
    assert result.outbound_text == body


def test_gateway_turn_blocks_a_reply_to_a_different_conversation() -> None:
    leaked = "Wrong thread - should never be delivered."
    final = "Sorry, I could not complete that."

    turn = run_gateway_turn(
        conversation_id="conv-A",
        inbound_body="Where is my order?",
        system_message="You are Toee Tire support.",
        scripted_completions=[
            {
                "tool_calls": [
                    {
                        "name": "toee_textline_reply__send_message",
                        "arguments": {"conversation_id": "conv-B", "body": leaked},
                    }
                ]
            },
            {"content": final},
        ],
    )

    result = _replay(turn)

    # The send to a non-bound conversation is a governed policy_blocked failure.
    assert result.tool_calls[0].ok is False
    # A blocked send produces no customer-facing body, so the leaked text is never
    # delivered; outbound text falls back to the agent's final_response (ADR-0083).
    assert leaked not in result.outbound_text
    assert result.outbound_text == final
