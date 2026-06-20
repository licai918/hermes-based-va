"""Launch Eval JSON report (ports report.ts, ADR-0074).

The standard report is the source of truth for ``toee_eval_review`` and the CI
artifact trail: per-scenario pass/fail with the failed assertions, a summary
bucketed by severity, and a ``signoff_required`` flag set when medium-severity
scenarios fail (high-severity failures block promotion outright at the CLI).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from .assertions import AssertionOutcome
from .types import EvalSeverity


@dataclass(frozen=True)
class FailedAssertion:
    type: str
    name: str
    detail: str


@dataclass(frozen=True)
class ScenarioReport:
    scenario_id: str
    title: str
    passed: bool
    severity: EvalSeverity
    failed_assertions: list[FailedAssertion]


@dataclass(frozen=True)
class EvalReportSummary:
    total: int
    passed: int
    failed_high: int
    failed_medium: int


@dataclass(frozen=True)
class EvalReport:
    run_id: str
    suite: str
    model_slug: str
    prompt_version: str
    knowledge_version: str
    scenarios: list[ScenarioReport]
    summary: EvalReportSummary
    signoff_required: bool


@dataclass(frozen=True)
class ScenarioOutcome:
    """Per-scenario evaluation result fed into the report builder."""

    scenario_id: str
    title: str
    severity: EvalSeverity
    outcomes: list[AssertionOutcome]


@dataclass(frozen=True)
class ReportMeta:
    run_id: Optional[str] = None
    model_slug: Optional[str] = None
    prompt_version: Optional[str] = None
    knowledge_version: Optional[str] = None


def build_report(
    suite: str,
    scenario_outcomes: list[ScenarioOutcome],
    meta: Optional[ReportMeta] = None,
) -> EvalReport:
    meta = meta or ReportMeta()

    scenarios: list[ScenarioReport] = []
    for scenario in scenario_outcomes:
        failed = [outcome for outcome in scenario.outcomes if not outcome.passed]
        scenarios.append(
            ScenarioReport(
                scenario_id=scenario.scenario_id,
                title=scenario.title,
                passed=len(failed) == 0,
                severity=scenario.severity,
                failed_assertions=[
                    FailedAssertion(
                        type=outcome.type, name=outcome.name, detail=outcome.detail
                    )
                    for outcome in failed
                ],
            )
        )

    failed_scenarios = [s for s in scenarios if not s.passed]
    summary = EvalReportSummary(
        total=len(scenarios),
        passed=len(scenarios) - len(failed_scenarios),
        failed_high=sum(1 for s in failed_scenarios if s.severity == "high"),
        failed_medium=sum(1 for s in failed_scenarios if s.severity == "medium"),
    )

    return EvalReport(
        run_id=meta.run_id or f"{suite}-{int(time.time() * 1000)}",
        suite=suite,
        model_slug=meta.model_slug or "stub",
        prompt_version=meta.prompt_version or "v0",
        knowledge_version=meta.knowledge_version or "v0",
        scenarios=scenarios,
        summary=summary,
        signoff_required=summary.failed_medium > 0,
    )


def write_report(eval_dir: str, report: EvalReport) -> str:
    """Write the report to ``<eval_dir>/reports/<run_id>.json`` and return the path."""
    reports_dir = Path(eval_dir) / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{report.run_id}.json"
    path.write_text(json.dumps(asdict(report), indent=2) + "\n", encoding="utf-8")
    return str(path)
