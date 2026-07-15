"""Tests for the S08 advisory judge wiring (PRD workspace/0.0.2/PRD.md §9, §6.2 R5/R6, PAC-4).

:func:`eval_runner.advisory.judge_scenario_leg` composes a scenario's transcript
(reply + ``memory_preset``) with the S06 judge — the freebie-killer's genuine
replacement (turn_result.py no longer forces ``honored_injected_preference=True``;
assertions.py no longer auto-passes ``honor_injected_preference``, see
test_eval_turn_result.py / test_eval_assertions.py). Every test here uses a stubbed
:class:`~eval_runner.judge.JudgeClient` (mirrors S06's own `_StubJudgeClient`), so
none of this makes a live LLM/network call. The module-sweep test at the bottom is
the proof this wiring never reaches the deterministic replay gate — the CRITICAL
invariant (PRD §9 decision 4): the judge is advisory, never gating, so CI cannot
flake on it.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from eval_runner.advisory import judge_scenario_leg
from eval_runner.fixtures import load_scenario
from eval_runner.harness import AgentTurnResult
from eval_runner.judge import JudgeVerdict

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


class _StubJudgeClient:
    """The injected model boundary — no network, mirrors eval_runner.judge's own tests."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.prompts: list[str] = []
        self.models: list[str] = []

    def complete(self, prompt: str, *, model: str) -> str:
        self.prompts.append(prompt)
        self.models.append(model)
        return self._response


def _result(text: str) -> AgentTurnResult:
    return AgentTurnResult(outbound_text=text)


# ---------------------------------------------------------------------------
# R5 — honored leg: the freebie is gone, this is the genuine replacement
# ---------------------------------------------------------------------------


def test_honored_leg_passes_for_a_genuinely_honoring_reply() -> None:
    scenario = load_scenario("text_first_launch", "25", EVAL_DIR)
    client = _StubJudgeClient('{"verdict": "yes", "reason": "acted on it"}')

    verdict = judge_scenario_leg(
        scenario,
        _result("Since you prefer after 2pm, I've queued the callback for then."),
        leg="honored",
        client=client,
    )

    assert verdict == JudgeVerdict(leg="honored", passed=True, reason="acted on it")


def test_honored_leg_fails_for_an_ignored_or_reasked_reply() -> None:
    # This is the fixture that would have passed for free before S08:
    # turn_result.py forced honored_injected_preference=True whenever
    # scenario.memory_preset was set, regardless of what the reply said.
    scenario = load_scenario("text_first_launch", "25", EVAL_DIR)
    client = _StubJudgeClient('{"verdict": "no", "reason": "re-asked instead"}')

    verdict = judge_scenario_leg(
        scenario,
        _result("Sure! What time works best for a callback?"),
        leg="honored",
        client=client,
    )

    assert verdict.passed is False


def test_judge_scenario_leg_sends_the_scenario_memory_preset_and_the_reply() -> None:
    scenario = load_scenario("text_first_launch", "25", EVAL_DIR)
    assert scenario.memory_preset, "scenario 25 fixture must inject a preference"
    client = _StubJudgeClient('{"verdict": "yes", "reason": "ok"}')

    judge_scenario_leg(
        scenario, _result("the actual reply text"), leg="honored", client=client
    )

    prompt = client.prompts[0]
    assert "the actual reply text" in prompt
    for value in scenario.memory_preset.values():
        assert value in prompt


# ---------------------------------------------------------------------------
# R6 — no-unprompted-recall leg
# ---------------------------------------------------------------------------


def test_no_unprompted_recall_leg_passes_when_the_reply_stays_silent() -> None:
    scenario = load_scenario("text_first_launch", "31", EVAL_DIR)
    client = _StubJudgeClient('{"verdict": "silent", "reason": "never mentioned it"}')

    verdict = judge_scenario_leg(
        scenario,
        _result("Order 1042 is in transit, arriving tomorrow afternoon."),
        leg="no_unprompted_recall",
        client=client,
    )

    assert verdict.passed is True


def test_no_unprompted_recall_leg_fails_when_the_reply_volunteers_the_preference() -> None:
    scenario = load_scenario("text_first_launch", "31", EVAL_DIR)
    client = _StubJudgeClient(
        '{"verdict": "recalled", "reason": "brought up contact time unprompted"}'
    )

    verdict = judge_scenario_leg(
        scenario,
        _result(
            "Order 1042 is in transit. By the way, I have you down for "
            "contact after 2pm Eastern."
        ),
        leg="no_unprompted_recall",
        client=client,
    )

    assert verdict.passed is False


# ---------------------------------------------------------------------------
# THE CRITICAL INVARIANT: advisory, never gating (PRD §9 decision 4)
# ---------------------------------------------------------------------------


def test_advisory_module_is_never_referenced_by_the_deterministic_gate_path() -> None:
    # Every module actually reachable from `python -m eval_runner --harness
    # replay` (cli -> run -> replay -> turn_result/transcript/disclosures/
    # harness -> assertions -> report; fixtures loads scenarios for all of
    # them) must never mention the judge — not import it, not call it, not
    # even name it in a comment that could paper over a real wiring. This is
    # the deterministic-gate half of S06's own scope-boundary test
    # (test_eval_judge.py::test_judge_module_is_not_wired_into_the_gating_assertion_package_yet),
    # widened here to the full reachable set now that S08 has actually built
    # the (separate, advisory-only) wiring the freebie's removal calls for.
    from eval_runner import (
        assertions,
        cli,
        disclosures,
        fixtures,
        harness,
        replay,
        report,
        run,
        turn_result,
    )

    deterministic_gate_modules = (
        cli,
        run,
        replay,
        turn_result,
        disclosures,
        harness,
        assertions,
        report,
        fixtures,
    )
    for module in deterministic_gate_modules:
        source = inspect.getsource(module).lower()
        assert "judge" not in source, (
            f"{module.__name__} must never mention the judge — it is advisory-only "
            "and must never run inside the deterministic replay gate (PRD §9 decision 4)."
        )


def test_judge_scenario_leg_never_raises_on_a_failing_verdict() -> None:
    # Advisory means advisory: a "no"/garbage verdict is a recorded JudgeVerdict,
    # never an exception this caller would have to guard against.
    scenario = load_scenario("text_first_launch", "25", EVAL_DIR)
    for response in ('{"verdict": "no", "reason": "nope"}', "not json at all", ""):
        client = _StubJudgeClient(response)
        verdict = judge_scenario_leg(
            scenario, _result("anything"), leg="honored", client=client
        )
        assert isinstance(verdict, JudgeVerdict)
