"""Live-turn bridge: a real Nous ``AIAgent`` turn closes the record/replay loop.

A live turn is driven by a deterministic provider seam (scripted ChatCompletions),
captured as ``{final_response, messages}`` exactly as ``run_agent`` returns, handed
to :func:`eval_runner.recorder.record_turn`, and replayed through
:class:`eval_runner.replay.ReplayAgentHarness` (ADR-0121, ADR-0139).

The LLM provider is the only fake — the unavoidable nondeterministic boundary. The
agent loop, turn capture, recorder, and replay parser are all real, so this proves
a recorded real-agent turn reproduces deterministically with no model or network.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from eval_runner.fixtures import load_scenario
from eval_runner.recorder import record_turn
from eval_runner.replay import ReplayAgentHarness

from hermes_runtime.live import run_live_turn

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


def test_live_turn_round_trips_through_record_and_replay() -> None:
    reply = "Thanks for reaching out to Toee Tire - how can I help with your order?"

    turn = run_live_turn(
        user_message="Hello?",
        system_message="You are Toee Tire support. Reply in one short sentence.",
        scripted_completions=[{"content": reply}],
    )

    # A real AIAgent loop ran and surfaced the model's final reply + message log.
    assert turn["final_response"].strip() == reply
    assert isinstance(turn["messages"], list) and turn["messages"]

    # The captured turn records and replays deterministically. With no Textline
    # send, the customer-facing text falls back to the agent's final_response.
    scenario = load_scenario("text_first_launch", "01", EVAL_DIR)
    with tempfile.TemporaryDirectory(prefix="live-turn-") as tmp:
        root = Path(tmp)
        record_turn(turn=turn, scenario=scenario, transcripts_dir=root)
        result = ReplayAgentHarness(root).run_turn(scenario)

    assert result.outbound_text.strip() == reply
