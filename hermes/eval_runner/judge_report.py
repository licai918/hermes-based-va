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

from typing import Mapping, Optional, Sequence

from .judge import JudgeLeg
from .judge_fixtures import JUDGE_FIXTURES, JudgeFixture
from .judge_measure import JudgeMetrics, held_out_effective_n_note

# Stable upsert key: the CI PR-comment step greps for this marker so a re-run
# edits the one advisory comment instead of posting a new one each time.
MARKER = "<!-- s20-advisory-judge-report -->"

# Every CALIBRATED leg, in report order -- deliberately wider than
# `hermes_runtime.honored_rate.JUDGE_LEGS`, which is the PRODUCTION-SAMPLING set.
# A leg is calibrated here as soon as it has labelled fixtures; it joins
# production sampling only once it can read something off a live transcript.
# `no_unprompted_recall` cannot (it needs the inbound turn) and `no_stale_use`
# cannot yet (nothing shipped renders supersession) -- see the comment on
# JUDGE_LEGS. Measuring a leg here costs fixtures, not billed production traffic,
# so the two lists are meant to differ.
_LEG_ORDER: tuple[JudgeLeg, ...] = (
    "honored",
    "no_unprompted_recall",
    "no_misapplication",
    "no_stale_use",
    "injection_resisted",
)

_ADVISORY_BANNER = (
    "**Advisory only — this never blocks merge.** The scripted replay gate stays the "
    "only required eval check (NFR-7). Flakes are data, not failures to suppress (FR-29)."
)

# S21 (0.0.5 FR-28). The banner above must not be read as "nothing about these
# legs can ever fail a build": the adversarial safety leg DOES gate — but via its
# deterministic twin in the replay gate (`assertions.safety.forbid_injected_
# instruction_obeyed`), not via this model-scored report. Spelling that out here
# keeps a reader from concluding either "the model gates CI" (it does not) or
# "an obeyed injection is advisory" (it is not).
_SAFETY_LEG_NOTE = (
    "The `injection_resisted` row is CALIBRATION for the one leg allowed to gate "
    "(NFR-4): an obeyed injected instruction is red with zero tolerance, enforced "
    "deterministically in the replay gate by the scenario's declared compliance "
    "markers, never by this model score. Its numbers here say how well a model "
    "reads that same property — nothing here gates."
)


# S21 review, finding 2. Nothing used to say the headline figure was in-sample
# after prompt tuning, which is exactly the claim contamination undermines.
_IN_SAMPLE_NOTE = (
    "**These are IN-SAMPLE numbers.** The per-leg grading rules in "
    "`judge._LEG_GUIDANCE` were written and tuned against these fixtures, so a "
    "high score here partly measures the prompt describing them. The held-out "
    "table below is the only evidence about shapes the rubric never named."
)

_HELD_OUT_NOTE = (
    "Fixtures deliberately built in failure shapes and memory renderings the "
    "rubric guidance does NOT describe — the honest read on whether the grader "
    "reads the property or recognises a described shape. Small n by "
    "construction: treat a miss here as a signal to look, not as a rate."
)

# S21 re-review: an ABSTENTION, not a flake. Precision and recall are computed
# over determinate verdicts only, so a leg renders 1.000/1.000 beside a fixture
# it never scored. Hence the `Undet.` column on every table below.
_UNDETERMINED_NOTE = (
    "`Undet.` is `undetermined/n` — verdicts the judge would not commit to. "
    "Precision and recall EXCLUDE them, so a rate of 1.000 next to a non-zero "
    "`Undet.` means the leg was perfect on what it scored and silent on the "
    "rest. A reproducible undetermined is an abstention, not a flake: read the "
    "two together or not at all."
)


def _rate_table_header() -> list[str]:
    return [
        "| Leg | Judged | Judge-correct | Misses | Precision | Recall | Undet. |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]


def _misses_table(metrics: JudgeMetrics) -> list[str]:
    if not metrics.misses:
        return ["_None — the judge matched every ground-truth label this run._"]
    lines = [
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
    return lines


def _held_out_section(
    metrics: JudgeMetrics, by_leg: Mapping[str, JudgeMetrics]
) -> list[str]:
    lines = [
        "",
        "### Held-out legs (reported separately, never averaged in)",
        "",
        _HELD_OUT_NOTE,
        "",
        held_out_effective_n_note(),
        "",
    ] + _rate_table_header()
    for leg in _LEG_ORDER:
        leg_metrics = by_leg.get(leg)
        if leg_metrics is None:
            continue
        lines.append(
            f"| `{leg}` | {leg_metrics.total} | {leg_metrics.correct} | "
            f"{len(leg_metrics.misses)} | {leg_metrics.precision:.3f} | "
            f"{leg_metrics.recall:.3f} | "
            f"{leg_metrics.undetermined}/{leg_metrics.total} |"
        )
    lines.append(
        f"| **all held-out** | {metrics.total} | {metrics.correct} | "
        f"{len(metrics.misses)} | {metrics.precision:.3f} | {metrics.recall:.3f} | "
        f"{metrics.undetermined}/{metrics.total} |"
    )
    # The held-out misses used to render as a bare COUNT (S21 re-review): the one
    # split that is not in-sample was the one you could not read a reason from.
    lines += ["", "#### Held-out misses", ""] + _misses_table(metrics)
    return lines


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
    by_leg: Optional[Mapping[str, JudgeMetrics]] = None,
    held_out: Optional[tuple[JudgeMetrics, Mapping[str, JudgeMetrics]]] = None,
) -> str:
    """Render a completed advisory judge run to markdown (verdicts, legs, misses).

    ``by_leg`` (S21, from :func:`eval_runner.judge_measure.measure_judge_legs`)
    adds per-leg precision/recall to the Legs table. It is optional so the
    pre-S21 single-metrics call still renders; without it the table falls back to
    judged/correct/miss counts only.

    ``held_out`` (S21 review) is the return value of a SECOND
    ``measure_judge_legs`` call over
    :func:`eval_runner.judge_measure.split_held_out`'s held-out subset. Supplied,
    it renders its own table; the two are never averaged, because the in-sample
    numbers are measured on the fixtures the rubric guidance was tuned against.
    """
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
            f"- In-sample: scored **{metrics.correct}/{metrics.total}** correct · "
            f"precision `{metrics.precision:.3f}` · recall `{metrics.recall:.3f}` · "
            f"accuracy `{metrics.accuracy:.3f}` · undetermined `{metrics.undetermined}`"
        ),
        "",
        "### Legs (in-sample)",
        "",
        _IN_SAMPLE_NOTE,
        "",
        _SAFETY_LEG_NOTE,
        "",
        _UNDETERMINED_NOTE,
        "",
    ]
    if by_leg is None:
        lines += [
            "| Leg | Judged | Judge-correct | Misses |",
            "| --- | ---: | ---: | ---: |",
        ]
    else:
        lines += _rate_table_header()
    for leg in _LEG_ORDER:
        judged = totals.get(leg, 0)
        misses = leg_misses.get(leg, 0)
        row = f"| `{leg}` | {judged} | {judged - misses} | {misses} |"
        if by_leg is not None:
            leg_metrics = by_leg.get(leg)
            row += (
                f" {leg_metrics.precision:.3f} | {leg_metrics.recall:.3f} | "
                f"{leg_metrics.undetermined}/{leg_metrics.total} |"
                if leg_metrics is not None
                else " — | — | — |"
            )
        lines.append(row)

    if held_out is not None:
        lines += _held_out_section(*held_out)

    lines += ["", "### Misses (in-sample; advisory — data, not a gate)", ""]
    lines += _misses_table(metrics)

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
    from .judge_measure import measure_judge_legs, split_held_out

    class _MockJudge:
        # A recorded/mock judge response: always "yes" — wrong on the ground-truth
        # negatives, so the render exercises the misses table + a <1.0 precision.
        def complete(self, prompt: str, *, model: str) -> str:
            return '{"verdict": "yes", "reason": "mock always-positive"}'

    judge = _MockJudge()
    in_sample, out_of_sample = split_held_out()
    metrics, by_leg = measure_judge_legs(in_sample, client=judge, model="mock/judge")
    report = render_report(
        metrics,
        model="mock/judge",
        fixtures=in_sample,
        by_leg=by_leg,
        held_out=measure_judge_legs(out_of_sample, client=judge, model="mock/judge"),
    )
    assert MARKER in report
    assert "Advisory only" in report
    assert "precision `" in report
    for leg in _LEG_ORDER:
        assert f"| `{leg}` |" in report
    assert "| Precision | Recall |" in report
    assert "IN-SAMPLE" in report and "all held-out" in report
    # Always-positive judge misses every ground-truth negative -> a non-empty misses table.
    assert metrics.misses and "Judge said" in report

    skipped = render_skipped("OPENROUTER_API_KEY not configured")
    assert MARKER in skipped and "Skipped:" in skipped and "never blocks" in skipped
    print("judge_report.demo: OK")


if __name__ == "__main__":  # pragma: no cover - thin self-check shell
    demo()
