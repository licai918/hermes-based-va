"""Launch Eval runner (ADR-0071, ADR-0121).

Python port of packages/eval-runner: load repository YAML fixtures, merge the
shared mock baseline, run each scenario through the agent harness, check the
standard assertion package, and emit the JSON go-live report. Runs against the
Python-native Domain Adapter Tools (ADR-0139).
"""

from __future__ import annotations

from .assertions import AssertionOutcome, evaluate_scenario
from .cli import CliArgs, main, parse_args
from .fixtures import (
    RESOLVED_AT,
    PolicySlotMap,
    load_base_mocks,
    load_policy_publish_suite,
    load_policy_slot_map,
    load_scenario,
    load_suite,
    parse_scenario_content,
    parse_scenario_file,
    resolve_scenario,
)
from .harness import (
    AgentHarness,
    AgentTurnResult,
    RecordedToolCall,
    build_scenario_registry,
    create_scenario_driver,
    scenario_execution_context,
    scenario_tool_gate,
    stub_agent_harness,
)
from .report import (
    EvalReport,
    EvalReportSummary,
    FailedAssertion,
    ReportMeta,
    ScenarioOutcome,
    ScenarioReport,
    build_report,
    write_report,
)
from .run import RunResult, run_suite
from .types import (
    BaseMocks,
    MergedMockContext,
    MergedScenario,
    ScenarioAssertions,
    ScenarioFixture,
    ScenarioTurn,
)

__all__ = [
    # fixtures
    "RESOLVED_AT",
    "PolicySlotMap",
    "load_base_mocks",
    "load_policy_publish_suite",
    "load_policy_slot_map",
    "load_scenario",
    "load_suite",
    "parse_scenario_content",
    "parse_scenario_file",
    "resolve_scenario",
    # types
    "BaseMocks",
    "MergedMockContext",
    "MergedScenario",
    "ScenarioAssertions",
    "ScenarioFixture",
    "ScenarioTurn",
    # harness
    "AgentHarness",
    "AgentTurnResult",
    "RecordedToolCall",
    "build_scenario_registry",
    "create_scenario_driver",
    "scenario_execution_context",
    "scenario_tool_gate",
    "stub_agent_harness",
    # assertions
    "AssertionOutcome",
    "evaluate_scenario",
    # report
    "EvalReport",
    "EvalReportSummary",
    "FailedAssertion",
    "ReportMeta",
    "ScenarioOutcome",
    "ScenarioReport",
    "build_report",
    "write_report",
    # run
    "RunResult",
    "run_suite",
    # cli
    "CliArgs",
    "main",
    "parse_args",
]
