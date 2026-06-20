"""Tests for the Launch Eval JSON report (ports runner.test.ts report blocks).

The report is the standard go-live artifact (ADR-0074): per-scenario pass/fail
with failed assertions, a severity-bucketed summary, and a ``signoff_required``
flag when medium-severity scenarios fail.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from eval_runner.assertions import AssertionOutcome
from eval_runner.report import (
    ReportMeta,
    ScenarioOutcome,
    build_report,
    write_report,
)


def test_build_report_summarizes_pass_fail_counts_by_severity() -> None:
    outcomes = [
        ScenarioOutcome(
            scenario_id="01",
            title="a",
            severity="medium",
            outcomes=[AssertionOutcome(type="tool", name="x", passed=True, detail="")],
        ),
        ScenarioOutcome(
            scenario_id="02",
            title="b",
            severity="high",
            outcomes=[
                AssertionOutcome(type="tool", name="y", passed=False, detail="nope")
            ],
        ),
        ScenarioOutcome(
            scenario_id="03",
            title="c",
            severity="medium",
            outcomes=[
                AssertionOutcome(type="text", name="z", passed=False, detail="nope")
            ],
        ),
    ]
    report = build_report("text_first_launch", outcomes, ReportMeta(run_id="test-run"))

    assert report.summary.total == 3
    assert report.summary.passed == 1
    assert report.summary.failed_high == 1
    assert report.summary.failed_medium == 1
    assert report.signoff_required is True
    assert report.run_id == "test-run"
    scenario_02 = next(s for s in report.scenarios if s.scenario_id == "02")
    assert len(scenario_02.failed_assertions) == 1


def test_build_report_defaults_metadata_and_signoff_when_all_pass() -> None:
    report = build_report("text_first_launch", [])
    assert report.suite == "text_first_launch"
    assert report.model_slug == "stub"
    assert report.prompt_version == "v0"
    assert report.knowledge_version == "v0"
    assert report.run_id.startswith("text_first_launch-")
    assert report.signoff_required is False
    assert report.summary.total == 0


def test_write_report_writes_json_under_reports_dir() -> None:
    with tempfile.TemporaryDirectory(prefix="eval-report-") as tmp:
        report = build_report("text_first_launch", [], ReportMeta(run_id="w1"))
        path = Path(write_report(tmp, report))

        assert path.parent.name == "reports"
        assert path.name == "w1.json"
        parsed = json.loads(path.read_text(encoding="utf-8"))
        assert parsed["run_id"] == "w1"
        assert parsed["summary"]["total"] == 0
