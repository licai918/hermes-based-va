"""Scenario-aware turn result: disclosure derivation (ADR-0072/0118).

``turn_result_from_transcript`` derives the channel-agnostic facts (tool calls, text,
case writes, memory upserts). The Launch Eval also asserts safety *disclosures* —
facts that need the scenario's channel. :func:`build_scenario_turn_result` layers
those on so the live recorder and the CI replay harness produce identical results
from one transcript. (S08: this module no longer derives an "honored" signal at
all — see :mod:`eval_runner.advisory` for the genuine, advisory-only replacement.)
"""

from __future__ import annotations

import json
from pathlib import Path

from eval_runner.fixtures import load_scenario
from eval_runner.turn_result import build_scenario_turn_result

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


def _qbo_messages(*, ok: bool) -> list[dict]:
    """A transcript with one ``toee_qbo_read.get_invoice`` call that succeeded/failed."""
    result = (
        {"invoice_id": "INV-9001", "balance": 1250}
        if ok
        else {"error": "blocked", "error_class": "policy_blocked"}
    )
    return [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "toee_qbo_read__get_invoice",
                        "arguments": json.dumps({"invoice_id": "INV-9001"}),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "name": "toee_qbo_read__get_invoice",
            "content": json.dumps(result),
        },
    ]


def test_no_account_disclosure_true_when_no_qbo_read() -> None:
    scenario = load_scenario("text_first_launch", "02", EVAL_DIR)
    result = build_scenario_turn_result(scenario, final_response="hi", messages=[])
    assert result.disclosures["no_account_disclosure"] is True


def test_no_account_disclosure_false_on_successful_qbo_read() -> None:
    scenario = load_scenario("text_first_launch", "01", EVAL_DIR)
    result = build_scenario_turn_result(
        scenario, final_response="", messages=_qbo_messages(ok=True)
    )
    assert result.disclosures["no_account_disclosure"] is False


def test_no_account_disclosure_true_when_qbo_read_was_gate_blocked() -> None:
    # Scenario 04: the QBO read is gate-blocked (email link failed). A *failed* read
    # surfaced no accounting data, so the disclosure invariant still holds.
    scenario = load_scenario("text_first_launch", "04", EVAL_DIR)
    result = build_scenario_turn_result(
        scenario, final_response="", messages=_qbo_messages(ok=False)
    )
    assert result.disclosures["no_account_disclosure"] is True


def test_script_and_directory_invariants_default_true() -> None:
    scenario = load_scenario("text_first_launch", "02", EVAL_DIR)
    result = build_scenario_turn_result(scenario, final_response="", messages=[])
    assert result.disclosures["no_registered_phone_script"] is True
    assert result.disclosures["no_employee_directory_leak"] is True


def test_memory_preset_presence_no_longer_forces_any_result_field() -> None:
    # S08: this module used to force honored_injected_preference=True onto the
    # result whenever scenario.memory_preset was set, regardless of what the
    # reply actually said (the freebie). The field is gone entirely now — a
    # genuine honored/silent signal only ever exists as the S06 judge's
    # advisory JudgeVerdict (eval_runner.advisory), never as a mechanical
    # AgentTurnResult field forced by preset presence alone.
    scenario = load_scenario("text_first_launch", "25", EVAL_DIR)
    assert scenario.memory_preset, "scenario 25 fixture must inject a preference"

    ignoring_reply = build_scenario_turn_result(
        scenario, final_response="What time works best for a callback?", messages=[]
    )
    honoring_reply = build_scenario_turn_result(
        scenario, final_response="Sure, I'll follow up after 2pm as you asked.", messages=[]
    )

    assert not hasattr(ignoring_reply, "honored_injected_preference")
    assert not hasattr(honoring_reply, "honored_injected_preference")


def test_email_channel_merges_structural_disclosure() -> None:
    scenario = load_scenario("email_go_live", "20", EVAL_DIR)
    result = build_scenario_turn_result(scenario, final_response="", messages=[])
    assert result.disclosures["no_sms_session_opener"] is True


def test_tool_calls_and_text_preserved_from_transcript() -> None:
    # build_scenario_turn_result must not drop the channel-agnostic facts.
    scenario = load_scenario("text_first_launch", "01", EVAL_DIR)
    result = build_scenario_turn_result(
        scenario, final_response="", messages=_qbo_messages(ok=True)
    )
    assert [(c.tool, c.action, c.ok) for c in result.tool_calls] == [
        ("toee_qbo_read", "get_invoice", True)
    ]
