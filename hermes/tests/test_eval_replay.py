"""Tests for the replay agent harness (deterministic record/replay CI path).

A recorded Hermes turn transcript (``{final_response, messages}``) lives under
``<transcripts_dir>/<suite>/<scenario_id>.json``. The replay harness loads it and
runs it through the transcript parser, so the eval gate can run a real agent's
captured behavior deterministically — no model, no network, no credentials.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from eval_runner.fixtures import load_scenario
from eval_runner.replay import ReplayAgentHarness, TranscriptNotFound

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


def _write_transcript(root: Path, suite: str, scenario_id: str, doc: dict) -> None:
    suite_dir = root / suite
    suite_dir.mkdir(parents=True, exist_ok=True)
    (suite_dir / f"{scenario_id}.json").write_text(json.dumps(doc), encoding="utf-8")


def test_replays_recorded_transcript_into_turn_result() -> None:
    scenario = load_scenario("text_first_launch", "01", EVAL_DIR)
    body = "Your invoice INV-9001 is paid in full."
    doc = {
        "final_response": "(internal)",
        "messages": [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "toee_sms_reply__send_message",
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
                "name": "toee_sms_reply__send_message",
                "content": json.dumps(
                    {"message_id": "m1", "conversation_id": "conv1", "body": body}
                ),
            },
        ],
    }
    with tempfile.TemporaryDirectory(prefix="eval-replay-") as tmp:
        root = Path(tmp)
        _write_transcript(root, scenario.suite, scenario.scenario_id, doc)
        result = ReplayAgentHarness(root).run_turn(scenario)

    assert result.outbound_text == body
    assert [(c.tool, c.action) for c in result.tool_calls] == [
        ("toee_sms_reply", "send_message")
    ]


def test_email_replay_populates_channel_derived_disclosures() -> None:
    # ADR-0056: the email channel structurally satisfies no_sms_session_opener,
    # which the pure transcript composer cannot know (it lacks scenario channel),
    # so the replay harness must merge it from the scenario.
    scenario = load_scenario("email_go_live", "20", EVAL_DIR)
    assert scenario.channel == "email"
    doc = {"final_response": "Thanks for reaching out to Toee Tire support.", "messages": []}
    with tempfile.TemporaryDirectory(prefix="eval-replay-") as tmp:
        root = Path(tmp)
        _write_transcript(root, scenario.suite, scenario.scenario_id, doc)
        result = ReplayAgentHarness(root).run_turn(scenario)

    assert result.disclosures.get("no_sms_session_opener") is True


def test_missing_transcript_raises_transcript_not_found() -> None:
    scenario = load_scenario("text_first_launch", "01", EVAL_DIR)
    with tempfile.TemporaryDirectory(prefix="eval-replay-") as tmp:
        harness = ReplayAgentHarness(Path(tmp))
        with pytest.raises(TranscriptNotFound):
            harness.run_turn(scenario)
