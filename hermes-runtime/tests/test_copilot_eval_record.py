"""Copilot-path Launch Eval recording adapter (S07, PRD FR-3/R4).

:func:`hermes_runtime.copilot_eval_record.record_copilot_scenario_turn` drives one
UNBOUND internal_copilot draft turn for a scenario (mirrors
``hermes_runtime.eval_record.record_scenario_turn`` for the External/bound path),
persists/parses it through the eval runner's UNCHANGED ``record_turn`` /
``build_scenario_turn_result``, and returns the parsed AgentTurnResult -- proving
scenario 30 (the copilot no-inferred-write regression) can be recorded and replayed
through the existing eval_runner package with zero changes there (S05 spike).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from eval_runner.fixtures import load_scenario
from eval_runner.replay import ReplayAgentHarness

from hermes_runtime.copilot_eval_record import (
    record_copilot_scenario_turn,
    scenario_copilot_prompt,
)

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


def test_scenario_copilot_prompt_is_the_bare_inbound_text() -> None:
    # Unlike the External recorder's scenario_user_message, the copilot prompt
    # carries NO injected identity/memory block -- the copilot turn injects memory
    # itself and never surfaces identity as a snapshot (ADR-0147 decision 2);
    # prepending one here would double-inject it in front of the model.
    scenario = load_scenario("text_first_launch", "30", EVAL_DIR)
    assert scenario_copilot_prompt(scenario) == "What's the status of order 1042?"


def test_record_copilot_scenario_turn_persists_and_replays_a_clean_transcript() -> None:
    # The well-behaved draft: no memory tool call at all. Proves the adapter's
    # store -> make_copilot_run_turn -> record_turn -> build_scenario_turn_result
    # pipeline round-trips through the UNCHANGED eval_runner package end to end.
    scenario = load_scenario("text_first_launch", "30", EVAL_DIR)
    reply = "Your order #1042 is in transit -- let me know if you need anything else!"

    with tempfile.TemporaryDirectory(prefix="copilot-eval-rec-") as tmp:
        root = Path(tmp)
        path, result = record_copilot_scenario_turn(
            scenario,
            transcripts_dir=root,
            scripted_completions=[{"content": reply}],
        )

        assert path.is_file()
        replayed = ReplayAgentHarness(root).run_turn(scenario)

    assert result.outbound_text.strip() == reply
    assert result.memory_upserts == []
    assert not any(
        c.tool == "toee_customer_memory" and c.action == "upsert_preference"
        for c in result.tool_calls
    )
    assert replayed.outbound_text.strip() == reply


def test_record_copilot_scenario_turn_surfaces_an_inferred_write_if_the_model_makes_one() -> None:
    # Negative control: proves the plumbing actually threads the tool-call
    # transcript through (not just the final text), so a regression that silently
    # drops it again would be caught. This is exactly the failure
    # forbid_inferred_upsert (assertions.py, unmodified) is there to catch.
    scenario = load_scenario("text_first_launch", "30", EVAL_DIR)

    with tempfile.TemporaryDirectory(prefix="copilot-eval-rec-") as tmp:
        _, result = record_copilot_scenario_turn(
            scenario,
            transcripts_dir=Path(tmp),
            scripted_completions=[
                {
                    "tool_calls": [
                        {
                            "name": "toee_customer_memory__upsert_preference",
                            "arguments": {"key": "contact_time_preference", "value": "mornings"},
                        }
                    ]
                },
                {"content": "Noted -- mornings work best going forward."},
            ],
        )

    assert any(
        c.tool == "toee_customer_memory" and c.action == "upsert_preference"
        for c in result.tool_calls
    )
