"""Launch Eval runner (ports run.ts, ADR-0121).

Selects the scenarios for a run (whole suite, a single scenario, or a policy
slot's set plus the regression subset), runs each through the agent harness
(stub by default), checks the standard assertion package, and assembles the JSON
report. The CLI sets ``write=True`` to persist it under ``eval/reports``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .assertions import evaluate_scenario
from .fixtures import (
    PathLike,
    load_policy_publish_suite,
    load_scenario,
    load_suite,
)
from .harness import AgentHarness, stub_agent_harness
from .report import EvalReport, ReportMeta, ScenarioOutcome, build_report, write_report
from .types import MergedScenario


@dataclass(frozen=True)
class RunResult:
    report: EvalReport
    report_path: Optional[str] = None


def _select_scenarios(
    *,
    suite: str,
    eval_dir: PathLike,
    scenario_id: Optional[str],
    slot: Optional[str],
) -> list[MergedScenario]:
    if suite == "policy_publish":
        if slot is None:
            raise ValueError("policy_publish runs require a --slot.")
        return load_policy_publish_suite(eval_dir, slot)
    if scenario_id is not None:
        return [load_scenario(suite, scenario_id, eval_dir)]
    return load_suite(suite, eval_dir)


def run_suite(
    *,
    suite: str,
    eval_dir: PathLike,
    scenario_id: Optional[str] = None,
    slot: Optional[str] = None,
    agent: Optional[AgentHarness] = None,
    meta: Optional[ReportMeta] = None,
    write: bool = False,
) -> RunResult:
    active_agent = agent or stub_agent_harness
    scenarios = _select_scenarios(
        suite=suite, eval_dir=eval_dir, scenario_id=scenario_id, slot=slot
    )

    scenario_outcomes: list[ScenarioOutcome] = []
    for scenario in scenarios:
        turn = active_agent.run_turn(scenario)
        scenario_outcomes.append(
            ScenarioOutcome(
                scenario_id=scenario.scenario_id,
                title=scenario.title,
                severity=scenario.assertions.max_severity,
                outcomes=evaluate_scenario(scenario, turn),
            )
        )

    report = build_report(suite, scenario_outcomes, meta)
    report_path = write_report(str(eval_dir), report) if write else None
    return RunResult(report=report, report_path=report_path)
