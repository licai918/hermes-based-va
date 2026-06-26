"""Tests for the Launch Eval assertion engine (ports assertions.test.ts, ADR-0072).

Runs the standard assertion package (behavioral / tool / disclosure / text /
memory) against an agent turn result and returns one outcome per checked
assertion; a failed outcome fails the scenario at its ``max_severity``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from eval_runner.assertions import AssertionOutcome, evaluate_scenario
from eval_runner.harness import AgentTurnResult, RecordedToolCall
from eval_runner.types import ScenarioAssertions


def _scenario_with(assertions: ScenarioAssertions) -> Any:
    # evaluate_scenario only reads scenario.assertions (matches the TS cast).
    return SimpleNamespace(assertions=assertions)


def _turn(**overrides: Any) -> AgentTurnResult:
    return AgentTurnResult(**overrides)


def _failures(outcomes: list[AssertionOutcome]) -> list[AssertionOutcome]:
    return [outcome for outcome in outcomes if not outcome.passed]


# --- behavioral ---------------------------------------------------------------


def test_behavioral_passes_when_case_created_matches() -> None:
    outcomes = evaluate_scenario(
        _scenario_with(
            ScenarioAssertions(behavioral={"case_created": True}, max_severity="high")
        ),
        _turn(case_created=True),
    )
    assert _failures(outcomes) == []


def test_behavioral_fails_when_case_created_mismatches() -> None:
    outcomes = evaluate_scenario(
        _scenario_with(
            ScenarioAssertions(behavioral={"case_created": True}, max_severity="high")
        ),
        _turn(case_created=False),
    )
    assert len(_failures(outcomes)) == 1


# --- tool ---------------------------------------------------------------------

_TOOL_ASSERTIONS = ScenarioAssertions(
    tool={
        "expect_calls": [{"tool": "toee_shopify_read", "action": "get_order"}],
        "forbidden_tools": [
            {"tool": "toee_square_payment_link", "action": "send_payment_link"}
        ],
    },
    max_severity="high",
)


def test_tool_passes_when_expected_called_and_forbidden_absent() -> None:
    outcomes = evaluate_scenario(
        _scenario_with(_TOOL_ASSERTIONS),
        _turn(
            tool_calls=[
                RecordedToolCall(tool="toee_shopify_read", action="get_order", ok=True)
            ]
        ),
    )
    assert _failures(outcomes) == []


def test_tool_fails_when_expected_call_missing() -> None:
    outcomes = evaluate_scenario(_scenario_with(_TOOL_ASSERTIONS), _turn())
    assert any("expect_call" in o.name for o in _failures(outcomes))


def test_tool_fails_when_forbidden_call_made() -> None:
    outcomes = evaluate_scenario(
        _scenario_with(_TOOL_ASSERTIONS),
        _turn(
            tool_calls=[
                RecordedToolCall(tool="toee_shopify_read", action="get_order", ok=True),
                RecordedToolCall(
                    tool="toee_square_payment_link",
                    action="send_payment_link",
                    ok=True,
                ),
            ]
        ),
    )
    assert any("forbidden" in o.name for o in _failures(outcomes))


# --- disclosure & text --------------------------------------------------------


def test_disclosure_checked_against_harness_reported_satisfaction() -> None:
    assertions = ScenarioAssertions(
        disclosure={"no_account_disclosure": True}, max_severity="high"
    )
    assert (
        _failures(
            evaluate_scenario(
                _scenario_with(assertions),
                _turn(disclosures={"no_account_disclosure": True}),
            )
        )
        == []
    )
    assert (
        len(_failures(evaluate_scenario(_scenario_with(assertions), _turn()))) == 1
    )


def test_text_must_contain_and_must_not_contain_case_insensitive() -> None:
    assertions = ScenarioAssertions(
        text={"must_contain": ["order number"], "must_not_contain": ["1250"]},
        max_severity="medium",
    )
    assert (
        _failures(
            evaluate_scenario(
                _scenario_with(assertions),
                _turn(outbound_text="Please share your ORDER NUMBER."),
            )
        )
        == []
    )
    bad = _failures(
        evaluate_scenario(
            _scenario_with(assertions),
            _turn(outbound_text="Your balance is 1250 today."),
        )
    )
    # must_contain missing AND must_not_contain present.
    assert len(bad) == 2


# --- memory -------------------------------------------------------------------


def test_memory_expect_upsert_and_slot_pass_when_slot_upserted() -> None:
    assertions = ScenarioAssertions(
        memory_assertions={
            "expect_upsert": True,
            "expect_upsert_slot": "contact_time_preference",
        },
        max_severity="high",
    )
    assert (
        _failures(
            evaluate_scenario(
                _scenario_with(assertions),
                _turn(memory_upserts=["contact_time_preference"]),
            )
        )
        == []
    )
    assert (
        len(_failures(evaluate_scenario(_scenario_with(assertions), _turn()))) == 2
    )


def test_memory_forbid_inferred_upsert_passes_only_when_no_upsert() -> None:
    assertions = ScenarioAssertions(
        memory_assertions={"forbid_inferred_upsert": True}, max_severity="high"
    )
    assert _failures(evaluate_scenario(_scenario_with(assertions), _turn())) == []
    assert (
        len(
            _failures(
                evaluate_scenario(
                    _scenario_with(assertions),
                    _turn(
                        tool_calls=[
                            RecordedToolCall(
                                tool="toee_customer_memory",
                                action="upsert_preference",
                                ok=True,
                            )
                        ]
                    ),
                )
            )
        )
        == 1
    )


def test_memory_honor_injected_preference_passes_only_when_reported() -> None:
    assertions = ScenarioAssertions(
        memory_assertions={"honor_injected_preference": True}, max_severity="medium"
    )
    assert (
        _failures(
            evaluate_scenario(
                _scenario_with(assertions),
                _turn(honored_injected_preference=True),
            )
        )
        == []
    )
    assert (
        len(_failures(evaluate_scenario(_scenario_with(assertions), _turn()))) == 1
    )
