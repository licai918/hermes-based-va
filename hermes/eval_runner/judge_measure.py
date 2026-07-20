"""Measures the judge's own precision/recall against JUDGE_FIXTURES (S27, PRD FR-29).

Feeds each :class:`eval_runner.judge_fixtures.JudgeFixture` through the real
:func:`eval_runner.judge.judge_reply` call (the exact function production callers
use) and scores the returned :class:`~eval_runner.judge.JudgeVerdict` against the
fixture's ground truth. ``client`` is the injected :class:`~eval_runner.judge.JudgeClient`
boundary -- a FAKE client makes this CI-safe and deterministic (see
``hermes/tests/test_eval_judge_measure.py``); a live OpenRouter-backed client
(constructed outside this dependency-free package, e.g.
``hermes_runtime.judge_eval.OpenRouterJudgeClient``) makes this a real measurement
run, same code path either way.

The fixture set spans two different legs, each with its own "positive" meaning
(``honored`` / ``silent``). Precision/recall here treat ``expected_passed=True`` as
the positive class uniformly across both legs -- a simplification, but the right
one for a single "how much do I trust this judge" number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from .judge import JudgeClient, judge_reply
from .judge_fixtures import JUDGE_FIXTURES, JudgeFixture


@dataclass(frozen=True)
class JudgeMiss:
    """One fixture the judge scored wrong (or couldn't score at all)."""

    fixture: JudgeFixture
    got_passed: Optional[bool]
    reason: str


@dataclass(frozen=True)
class JudgeMetrics:
    total: int
    correct: int
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    undetermined: int
    misses: tuple[JudgeMiss, ...]

    @property
    def precision(self) -> float:
        denominator = self.true_positives + self.false_positives
        return self.true_positives / denominator if denominator else 0.0

    @property
    def recall(self) -> float:
        denominator = self.true_positives + self.false_negatives
        return self.true_positives / denominator if denominator else 0.0

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0


def measure_judge(
    fixtures: Sequence[JudgeFixture] = JUDGE_FIXTURES,
    *,
    client: JudgeClient,
    model: Optional[str] = None,
) -> JudgeMetrics:
    """Score ``client`` against ``fixtures``' ground truth. Never raises.

    ``model`` is forwarded to :func:`eval_runner.judge.judge_reply` unchanged
    (``None`` resolves the usual way -- ``EVAL_JUDGE_MODEL`` or the cheap
    default), so a caller measuring a stronger configured model just passes
    it here.
    """
    true_positives = false_positives = 0
    true_negatives = false_negatives = 0
    undetermined = correct = 0
    misses: list[JudgeMiss] = []

    for fixture in fixtures:
        verdict = judge_reply(
            reply=fixture.reply,
            leg=fixture.leg,
            injected_memory=fixture.memory_preset,
            client=client,
            model=model,
        )
        got = verdict.passed
        if got is None:
            undetermined += 1
            misses.append(JudgeMiss(fixture, got, verdict.reason))
            continue
        if got == fixture.expected_passed:
            correct += 1
            if got:
                true_positives += 1
            else:
                true_negatives += 1
        else:
            misses.append(JudgeMiss(fixture, got, verdict.reason))
            if got:
                false_positives += 1
            else:
                false_negatives += 1

    return JudgeMetrics(
        total=len(fixtures),
        correct=correct,
        true_positives=true_positives,
        false_positives=false_positives,
        true_negatives=true_negatives,
        false_negatives=false_negatives,
        undetermined=undetermined,
        misses=tuple(misses),
    )
