"""Render the advisory judge run into a PR-ready markdown report (S20, FR-28/FR-29).

The S27 harness (:func:`eval_runner.judge_measure.measure_judge`) scores the tuned
judge over the labelled scenario set and returns a :class:`~eval_runner.judge_measure.JudgeMetrics`.
This module turns that into the human-facing artifact FR-28 attaches to every PR:
verdicts (precision/recall/accuracy), the per-leg honored / no-unprompted-recall
breakdown, and each miss — always framed as **advisory, never a gate**.

Dependency boundary (mirrors the rest of ``eval_runner``): pure formatting, no
network, no ``hermes_runtime`` import. The live client + graceful key-skip live one
layer out, in ``hermes_runtime.advisory_judge_report``; this module is unit-tested
by feeding a mock/recorded judge response through ``measure_judge`` (see
``hermes/tests/test_eval_judge_report.py``), so the rendering is covered with no key.

FR-29 stance baked into the copy: flakes are data, not failures to suppress, and the
report never blocks the required replay gate (NFR-7) — the markdown says so on its
face so a reader never mistakes an advisory miss for a merge blocker.
"""

from __future__ import annotations

from typing import Optional, Sequence

from .judge import JudgeLeg
from .judge_fixtures import JUDGE_FIXTURES, JudgeFixture
from .judge_measure import JudgeMetrics

# Stable upsert key: the CI PR-comment step greps for this marker so a re-run
# edits the one advisory comment instead of posting a new one each time.
MARKER = "<!-- s20-advisory-judge-report -->"

_LEG_ORDER: tuple[JudgeLeg, ...] = ("honored", "no_unprompted_recall")

_ADVISORY_BANNER = (
    "**Advisory only — this never blocks merge.** The scripted replay gate stays the "
    "only required eval check (NFR-7). Flakes are data, not failures to suppress (FR-29)."
)


def _leg_totals(fixtures: Sequence[JudgeFixture]) -> dict[str, int]:
    totals: dict[str, int] = {leg: 0 for leg in _LEG_ORDER}
    for fixture in fixtures:
        totals[fixture.leg] = totals.get(fixture.leg, 0) + 1
    return totals


def _leg_misses(metrics: JudgeMetrics) -> dict[str, int]:
    counts: dict[str, int] = {leg: 0 for leg in _LEG_ORDER}
    for miss in metrics.misses:
        counts[miss.fixture.leg] = counts.get(miss.fixture.leg, 0) + 1
    return counts


def render_report(
    metrics: JudgeMetrics,
    *,
    model: str,
    fixtures: Sequence[JudgeFixture] = JUDGE_FIXTURES,
) -> str:
    """Render a completed advisory judge run to markdown (verdicts, legs, misses)."""
    totals = _leg_totals(fixtures)
    leg_misses = _leg_misses(metrics)

    lines = [
        MARKER,
        "## Advisory judge report — live model over the scenario set (S20)",
        "",
        _ADVISORY_BANNER,
        "",
        f"- Judge model: `{model}`",
        (
            f"- Scored **{metrics.correct}/{metrics.total}** correct · "
            f"precision `{metrics.precision:.3f}` · recall `{metrics.recall:.3f}` · "
            f"accuracy `{metrics.accuracy:.3f}` · undetermined `{metrics.undetermined}`"
        ),
        "",
        "### Legs",
        "",
        "| Leg | Judged | Judge-correct | Misses |",
        "| --- | ---: | ---: | ---: |",
    ]
    for leg in _LEG_ORDER:
        judged = totals.get(leg, 0)
        misses = leg_misses.get(leg, 0)
        lines.append(f"| `{leg}` | {judged} | {judged - misses} | {misses} |")

    lines += ["", "### Misses (advisory — data, not a gate)", ""]
    if metrics.misses:
        lines += [
            "| Fixture | Leg | Expected | Judge said | Reason |",
            "| --- | --- | :---: | :---: | --- |",
        ]
        for miss in metrics.misses:
            got = "undetermined" if miss.got_passed is None else str(miss.got_passed)
            reason = miss.reason.replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {miss.fixture.name} | `{miss.fixture.leg}` | "
                f"{miss.fixture.expected_passed} | {got} | {reason} |"
            )
    else:
        lines.append("_None — the judge matched every ground-truth label this run._")

    lines += [
        "",
        "---",
        (
            "_Gate promotion (making this a required check) is a future ADR contingent "
            "on measured judge precision — see ADR-0159. Today: advisory forever._"
        ),
        "",
    ]
    return "\n".join(lines)


def render_skipped(reason: str, *, marker: str = MARKER) -> str:
    """Render the graceful-skip report (no live key) — still exit 0, never blocks."""
    return "\n".join(
        [
            marker,
            "## Advisory judge report — skipped (S20)",
            "",
            f"**Skipped:** {reason}",
            "",
            _ADVISORY_BANNER,
            "",
            "_This job lights up automatically once `OPENROUTER_API_KEY` is configured "
            "as a repo secret; until then it skips cleanly and never blocks a PR._",
            "",
        ]
    )


def demo() -> None:  # ponytail: one runnable self-check, no framework
    """Self-check: render both paths from a mock-driven metrics object."""
    from .judge_measure import measure_judge

    class _MockJudge:
        # A recorded/mock judge response: always "yes" — wrong on the ground-truth
        # negatives, so the render exercises the misses table + a <1.0 precision.
        def complete(self, prompt: str, *, model: str) -> str:
            return '{"verdict": "yes", "reason": "mock always-positive"}'

    metrics = measure_judge(client=_MockJudge(), model="mock/judge")
    report = render_report(metrics, model="mock/judge")
    assert MARKER in report
    assert "Advisory only" in report
    assert "precision `" in report
    assert "| `honored` |" in report
    assert "| `no_unprompted_recall` |" in report
    # Always-positive judge misses every ground-truth negative -> a non-empty misses table.
    assert metrics.misses and "Judge said" in report

    skipped = render_skipped("OPENROUTER_API_KEY not configured")
    assert MARKER in skipped and "Skipped:" in skipped and "never blocks" in skipped
    print("judge_report.demo: OK")


if __name__ == "__main__":  # pragma: no cover - thin self-check shell
    demo()
