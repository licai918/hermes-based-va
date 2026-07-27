"""Tests for the S20 advisory judge report renderer (FR-28/FR-29, NFR-7).

The renderer (:mod:`eval_runner.judge_report`) turns a judge run into the PR-ready
advisory markdown. Every test here drives it through a MOCK/recorded judge response
fed to :func:`eval_runner.judge_measure.measure_judge` -- no live model, no key, no
network -- which is exactly how the real-model path's rendering is verified without
``OPENROUTER_API_KEY`` (the live path itself is owner-key-gated and untestable here).
"""

from __future__ import annotations

from eval_runner.judge_fixtures import JUDGE_FIXTURES
from eval_runner.judge_measure import measure_judge, measure_judge_legs
from eval_runner.judge_report import MARKER, render_report, render_skipped


class _RecordedJudge:
    """Replays one canned response for every fixture -- the recorded-judge stand-in."""

    def __init__(self, response: str) -> None:
        self._response = response

    def complete(self, prompt: str, *, model: str) -> str:
        return self._response


class _OracleJudge:
    """Answers each fixture's own ground truth -- a perfect judge (no misses)."""

    def __init__(self) -> None:
        self._by_reply = {f.reply: f.expected_passed for f in JUDGE_FIXTURES}

    def complete(self, prompt: str, *, model: str) -> str:
        for reply, expected in self._by_reply.items():
            if reply in prompt:
                return f'{{"verdict": "{"yes" if expected else "no"}", "reason": "oracle"}}'
        return '{"verdict": "undetermined", "reason": "unknown"}'


def test_report_has_marker_advisory_banner_and_verdict_summary() -> None:
    metrics = measure_judge(client=_OracleJudge(), model="mock/judge")

    report = render_report(metrics, model="mock/judge")

    # Upsert marker (one comment, not spam) + the never-blocks framing (NFR-7/FR-29).
    assert report.startswith(MARKER)
    assert "Advisory only" in report
    assert "never blocks merge" in report
    assert "NFR-7" in report and "FR-29" in report
    # Verdicts: an oracle scores perfectly.
    assert "precision `1.000`" in report
    assert "recall `1.000`" in report


def test_report_breaks_out_every_leg() -> None:
    metrics = measure_judge(client=_OracleJudge(), model="mock/judge")

    report = render_report(metrics, model="mock/judge")

    for leg in {f.leg for f in JUDGE_FIXTURES}:
        assert f"| `{leg}` |" in report


def test_per_leg_precision_and_recall_render_when_supplied() -> None:
    # S21 (FR-28): the calibration numbers the brief asks for are PER LEG.
    overall, by_leg = measure_judge_legs(client=_OracleJudge(), model="mock/judge")

    report = render_report(overall, model="mock/judge", by_leg=by_leg)

    assert "Precision" in report and "Recall" in report
    # An oracle scores 1.000 on every leg, rendered per row.
    assert report.count("1.000") >= len(by_leg)


def test_the_safety_leg_is_labelled_as_the_one_gating_leg() -> None:
    overall, by_leg = measure_judge_legs(client=_OracleJudge(), model="mock/judge")

    report = render_report(overall, model="mock/judge", by_leg=by_leg)

    # The advisory banner must not read as "nothing here can ever fail a build":
    # the safety leg's DETERMINISTIC twin gates the replay gate (NFR-4).
    assert "injection_resisted" in report
    assert "gate" in report.lower()


def test_misses_render_as_a_table_when_the_judge_is_wrong() -> None:
    # Always-"yes" is wrong on every ground-truth negative -> a populated misses table.
    metrics = measure_judge(client=_RecordedJudge('{"verdict":"yes","reason":"always"}'))

    report = render_report(metrics, model="mock/judge")

    negatives = [f for f in JUDGE_FIXTURES if f.expected_passed is False]
    assert negatives
    assert "| Fixture | Leg | Expected | Judge said | Reason |" in report
    assert len(metrics.misses) == len(negatives)
    # The recorded reason string surfaces for the reader.
    assert "always" in report


def test_no_misses_renders_the_clean_line_not_an_empty_table() -> None:
    metrics = measure_judge(client=_OracleJudge(), model="mock/judge")

    report = render_report(metrics, model="mock/judge")

    assert "_None" in report
    assert "| Fixture | Leg |" not in report


def test_undetermined_judge_is_reported_not_crashed() -> None:
    metrics = measure_judge(client=_RecordedJudge("not json at all"))

    report = render_report(metrics, model="mock/judge")

    assert f"undetermined `{len(JUDGE_FIXTURES)}`" in report
    assert "undetermined" in report  # in the misses table's "Judge said" column too


def test_skipped_report_is_clearly_non_blocking() -> None:
    report = render_skipped("advisory judge skipped — OPENROUTER_API_KEY not configured")

    assert report.startswith(MARKER)
    assert "Skipped:" in report
    assert "OPENROUTER_API_KEY" in report
    assert "never blocks" in report


def test_a_reason_with_a_pipe_does_not_break_the_table() -> None:
    class _PipeJudge:
        def complete(self, prompt: str, *, model: str) -> str:
            return '{"verdict":"yes","reason":"a | b | c"}'

    metrics = measure_judge(client=_PipeJudge())
    report = render_report(metrics, model="mock/judge")

    assert "a \\| b \\| c" in report
