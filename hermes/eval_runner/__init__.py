"""Launch Eval runner (ADR-0071, ADR-0121).

Python port of packages/eval-runner: load repository YAML fixtures, merge the
shared mock baseline, run each scenario through the agent harness, check the
standard assertion package, and emit the JSON go-live report. Runs against the
Python-native Domain Adapter Tools (ADR-0139).
"""

from __future__ import annotations

from .advisory import judge_scenario_leg
from .assertions import AssertionOutcome, evaluate_scenario
from .cli import CliArgs, build_agent, main, parse_args
from .disclosures import derive_disclosures
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
from .judge import (
    DATA_NOT_INSTRUCTIONS_MARKER,
    DEFAULT_JUDGE_MODEL,
    JudgeClient,
    JudgeLeg,
    JudgeVerdict,
    build_judge_prompt,
    judge_reply,
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
from .recorder import record_turn
from .replay import ReplayAgentHarness, TranscriptNotFound, transcript_path
from .run import RunResult, run_suite
from .transcript import turn_result_from_transcript
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
    # judge (S06 — advisory, injection-hardened; not wired into gating yet)
    "DATA_NOT_INSTRUCTIONS_MARKER",
    "DEFAULT_JUDGE_MODEL",
    "JudgeClient",
    "JudgeLeg",
    "JudgeVerdict",
    "build_judge_prompt",
    "judge_reply",
    # advisory (S08 — composes the judge against a scenario transcript; never
    # imported by the deterministic gate path: assertions/turn_result/replay/run/cli)
    "judge_scenario_leg",
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
    # record/replay
    "turn_result_from_transcript",
    "ReplayAgentHarness",
    "TranscriptNotFound",
    "transcript_path",
    "record_turn",
    "derive_disclosures",
    # cli
    "CliArgs",
    "build_agent",
    "main",
    "parse_args",
]
