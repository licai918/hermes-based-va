"""Tests for the Launch Eval runner (ports runner.test.ts runSuite block, ADR-0121).

``run_suite`` selects scenarios for a suite/scenario/slot, runs each through the
agent harness (stub by default), checks the standard assertion package, and
assembles the JSON report. The stub harness fails high-severity scenarios so the
go-live gate is provably blocking until the live agent is wired in.
"""

from __future__ import annotations

from pathlib import Path

from eval_runner.harness import AgentTurnResult, RecordedToolCall
from eval_runner.report import ReportMeta
from eval_runner.run import run_suite

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


class _FixedHarness:
    """A harness that returns one predetermined turn result for every scenario."""

    def __init__(self, result: AgentTurnResult) -> None:
        self._result = result

    def run_turn(self, scenario: object) -> AgentTurnResult:
        return self._result


def test_text_first_launch_stub_fails_high_severity_scenarios() -> None:
    result = run_suite(
        suite="text_first_launch", eval_dir=EVAL_DIR, meta=ReportMeta(run_id="stub-run")
    )
    report = result.report
    assert report.suite == "text_first_launch"
    assert report.summary.total >= 20
    # The empty stub turn cannot satisfy high-severity scenarios, proving the
    # go-live gate would block (non-zero exit) until a real harness is wired in.
    assert report.summary.failed_high > 0


def test_scenario_01_passes_when_harness_reports_expected_behavior() -> None:
    passing = _FixedHarness(
        AgentTurnResult(
            tool_calls=[
                RecordedToolCall(tool="toee_shopify_read", action="get_order", ok=True),
                RecordedToolCall(
                    tool="toee_easyroutes_read",
                    action="get_delivery_status",
                    ok=True,
                ),
                RecordedToolCall(tool="toee_qbo_read", action="get_invoice", ok=True),
            ],
            case_created=False,
            disclosures={"no_registered_phone_script": True},
        )
    )
    result = run_suite(
        suite="text_first_launch",
        scenario_id="01",
        eval_dir=EVAL_DIR,
        agent=passing,
        meta=ReportMeta(run_id="pass-01"),
    )
    report = result.report
    assert report.summary.total == 1
    assert report.summary.passed == 1
    assert report.summary.failed_high == 0
    assert report.scenarios[0].passed is True


def test_policy_publish_selects_slot_plus_regression_subset() -> None:
    result = run_suite(
        suite="policy_publish",
        slot="standard_exception_scripts",
        eval_dir=EVAL_DIR,
        meta=ReportMeta(run_id="policy-run"),
    )
    assert result.report.suite == "policy_publish"
    assert result.report.summary.total > 0


def test_policy_publish_without_slot_raises() -> None:
    import pytest

    with pytest.raises(ValueError, match="slot"):
        run_suite(suite="policy_publish", eval_dir=EVAL_DIR)


def test_runs_email_go_live_suite() -> None:
    result = run_suite(
        suite="email_go_live", eval_dir=EVAL_DIR, meta=ReportMeta(run_id="email-run")
    )
    assert result.report.suite == "email_go_live"
    assert len(result.report.scenarios) > 0
