"""Live eval recording harness: record a real AIAgent turn per scenario (ADR-0071).

:func:`hermes_runtime.eval_record.record_scenario_turn` boots the External profile
with the scenario's MockDriver + External-profile gate + Session Identity Snapshot
(``toee_hermes.plugin.register_eval`` via :func:`boot_profile_eval`), drives a real
``AIAgent`` loop through an injected model boundary (scripted here, real OpenRouter
in production), captures ``{final_response, messages}``, persists it for replay, and
returns the parsed :class:`AgentTurnResult`.

The LLM provider is the only fake. The agent loop, governed dispatch through the
scenario's driver, transcript capture, and replay parser are all real — so this
proves the recorder bridge wires the *scenario's* data, not the default mock.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from eval_runner.fixtures import load_scenario
from eval_runner.replay import ReplayAgentHarness

from hermes_runtime.eval_record import record_scenario_turn, scenario_user_message
from hermes_runtime.live import run_scripted_agent

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


def _scripted_run(scripted_completions):
    """An injected model boundary that drives the real loop against a scripted provider."""

    def run_turn(*, user_message, system_message, governed_tool_names):
        return run_scripted_agent(
            user_message=user_message,
            system_message=system_message,
            governed_tool_names=governed_tool_names,
            scripted_completions=scripted_completions,
        )

    return run_turn


def test_scenario_user_message_injects_identity_and_memory() -> None:
    # In eval the pre_llm_call providers are unwired, so the model never sees the
    # Session Identity Snapshot or injected memory. The recorder must put that context
    # into the turn itself (ADR-0043, ADR-0113) so disclosure/honored-preference
    # behavior is driven, mirroring production's pre_llm_call injection.
    scenario = load_scenario("text_first_launch", "25", EVAL_DIR)
    assert scenario.memory_preset, "scenario 25 should carry an injected preference"

    message = scenario_user_message(scenario)

    # Rendered exactly like production's pre_llm_call block (toee_hermes hooks).
    assert "Session Identity Snapshot:" in message
    for key, value in scenario.session_identity.items():
        assert f"- {key}: {value}" in message
    assert "Customer Memory (preferences):" in message
    for slot, value in scenario.memory_preset.items():
        assert f"- {slot}: {value}" in message

    # The inbound customer text is still present after the injected context.
    inbound = scenario.turns[0].inbound
    inbound_text = inbound if isinstance(inbound, str) else inbound.get("body", "")
    assert inbound_text in message


def test_scenario_user_message_without_memory_still_injects_identity() -> None:
    # A scenario with no injected preference still gets the identity snapshot but no
    # empty Customer Memory header.
    scenario = load_scenario("text_first_launch", "01", EVAL_DIR)
    message = scenario_user_message(scenario)
    assert "Session Identity Snapshot:" in message
    assert "Customer Memory (preferences):" not in message


def test_record_scenario_turn_dispatches_through_the_scenario_driver() -> None:
    # Scenario 13 forces shopify into a governed failure (mock_overrides shopify.error).
    # A recorded shopify read must therefore come back *failed*, proving the scenario's
    # error-injected MockDriver (not the default mock) backed the booted profile.
    scenario = load_scenario("text_first_launch", "13", EVAL_DIR)
    run_turn = _scripted_run(
        [
            {
                "tool_calls": [
                    {
                        "name": "toee_shopify_read__search_products",
                        "arguments": {"query": "All-Season 225/60R16"},
                    }
                ]
            },
            {"content": "That lookup is temporarily unavailable; I've opened a follow-up."},
        ]
    )

    with tempfile.TemporaryDirectory(prefix="eval-rec-") as tmp:
        root = Path(tmp)
        path, result = record_scenario_turn(
            scenario,
            run_turn=run_turn,
            transcripts_dir=root,
            system_message="You are Toee Tire support.",
        )

        assert path.is_file()
        replayed = ReplayAgentHarness(root).run_turn(scenario)

    shopify_calls = [c for c in result.tool_calls if c.tool == "toee_shopify_read"]
    assert shopify_calls, "the recorded turn made no shopify read"
    assert all(not c.ok for c in shopify_calls), "scenario driver did not force the failure"

    # The persisted transcript replays to the identical observable tool calls.
    assert [(c.tool, c.action, c.ok) for c in replayed.tool_calls] == [
        (c.tool, c.action, c.ok) for c in result.tool_calls
    ]


def test_record_scenario_turn_falls_back_to_final_response_text() -> None:
    # A pure-text turn (no governed Textline send) records, and the customer-facing
    # text falls back to the agent's final_response (ADR-0083) through the parser.
    scenario = load_scenario("text_first_launch", "01", EVAL_DIR)
    reply = "Happy to help with order 1042 - let me pull that up."
    run_turn = _scripted_run([{"content": reply}])

    with tempfile.TemporaryDirectory(prefix="eval-rec-") as tmp:
        root = Path(tmp)
        path, result = record_scenario_turn(
            scenario, run_turn=run_turn, transcripts_dir=root
        )
        assert path.is_file()
        replayed = ReplayAgentHarness(root).run_turn(scenario)

    assert result.outbound_text.strip() == reply
    assert replayed.outbound_text.strip() == reply
