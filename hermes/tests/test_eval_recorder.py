"""Tests for the transcript recorder (record half of the record/replay strategy).

The recorder persists a captured Hermes turn (``{final_response, messages}``, as
``run_agent`` returns) into the exact on-disk layout the replay harness reads, so
a recorded turn round-trips deterministically back into an ``AgentTurnResult``.
The real-agent boot/provider seam is a separate, dependency-gated adapter; this
covers the persistence contract it must satisfy.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from eval_runner.fixtures import load_scenario
from eval_runner.recorder import record_turn
from eval_runner.replay import ReplayAgentHarness

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


def test_recorded_turn_round_trips_through_replay() -> None:
    scenario = load_scenario("text_first_launch", "01", EVAL_DIR)
    body = "Your invoice INV-9001 is paid in full."
    turn = {
        "final_response": "(internal)",
        "messages": [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "toee_textline_reply__send_message",
                            "arguments": json.dumps(
                                {"conversation_id": "conv1", "body": body}
                            ),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "c1",
                "name": "toee_textline_reply__send_message",
                "content": json.dumps({"message_id": "m1", "body": body}),
            },
        ],
    }
    with tempfile.TemporaryDirectory(prefix="eval-record-") as tmp:
        root = Path(tmp)
        record_turn(turn=turn, scenario=scenario, transcripts_dir=root)
        result = ReplayAgentHarness(root).run_turn(scenario)

    assert result.outbound_text == body
    assert [(c.tool, c.action) for c in result.tool_calls] == [
        ("toee_textline_reply", "send_message")
    ]
