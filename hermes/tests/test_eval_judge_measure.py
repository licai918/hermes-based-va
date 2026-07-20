"""Tests for the S27 judge precision/recall harness (PRD FR-29).

:func:`eval_runner.judge_measure.measure_judge` feeds
:data:`eval_runner.judge_fixtures.JUDGE_FIXTURES` through a real
:class:`eval_runner.judge.JudgeClient` boundary and scores the returned
verdicts against each fixture's ground-truth label. Every test here uses a
FAKE client (deterministic, no network) -- this is the CI-safe half of the
S27 contract. A live client (real OpenRouter-backed model) is out of scope
for these tests; see the S27 report for the one-off live measurement.
"""

from __future__ import annotations

from eval_runner.judge import JudgeVerdict
from eval_runner.judge_fixtures import JUDGE_FIXTURES
from eval_runner.judge_measure import measure_judge


class _PerfectJudgeClient:
    """Always returns the fixture's own ground truth -- an oracle stand-in.

    Proves the measurement plumbing itself (scoring, precision/recall math)
    is correct: an oracle client must score 100% on its own labels.
    """

    def __init__(self, fixtures) -> None:
        self._by_reply = {f.reply: f.expected_passed for f in fixtures}
        self.models: list[str] = []

    def complete(self, prompt: str, *, model: str) -> str:
        self.models.append(model)
        for reply, expected in self._by_reply.items():
            if reply in prompt:
                token = "yes" if expected else "no"
                return f'{{"verdict": "{token}", "reason": "oracle"}}'
        raise AssertionError("prompt did not contain a known fixture reply")


class _AlwaysHonoredClient:
    """A maximally-conflated stand-in for the recorded 0.0.2 weakness.

    Always answers "yes"/"honored"/"silent" (the positive token for either
    leg) regardless of content -- the degenerate case of a judge that keys
    off surface tokens rather than reasoning about behavior. Proves the
    harness actually detects a bad judge instead of always reporting 100%.
    """

    def complete(self, prompt: str, *, model: str) -> str:
        return '{"verdict": "yes", "reason": "always positive"}'


def test_oracle_client_scores_perfectly_on_its_own_labels() -> None:
    client = _PerfectJudgeClient(JUDGE_FIXTURES)

    metrics = measure_judge(client=client)

    assert metrics.total == len(JUDGE_FIXTURES)
    assert metrics.correct == len(JUDGE_FIXTURES)
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.misses == ()


def test_a_degenerate_always_positive_client_scores_below_perfect() -> None:
    # Some fixtures have expected_passed=False (not-honored, unprompted-recall
    # violations, and the "eta-only" conflation direction) -- an
    # always-positive judge must miss every one of those, so recall may stay
    # high but precision/accuracy must visibly drop.
    client = _AlwaysHonoredClient()

    metrics = measure_judge(client=client)

    negative_fixtures = [f for f in JUDGE_FIXTURES if f.expected_passed is False]
    assert negative_fixtures, "fixture set must include ground-truth-False cases"
    assert metrics.correct < metrics.total
    assert metrics.precision < 1.0
    assert len(metrics.misses) == len(negative_fixtures)


def test_measure_judge_passes_the_resolved_model_to_the_client() -> None:
    class _RecordingClient:
        def __init__(self) -> None:
            self.models: list[str] = []

        def complete(self, prompt: str, *, model: str) -> str:
            self.models.append(model)
            return '{"verdict": "undetermined", "reason": "n/a"}'

    client = _RecordingClient()

    measure_judge(client=client, model="anthropic/claude-opus-4")

    assert client.models
    assert set(client.models) == {"anthropic/claude-opus-4"}


def test_undetermined_verdicts_are_recorded_as_misses_not_a_crash() -> None:
    class _GarbageClient:
        def complete(self, prompt: str, *, model: str) -> str:
            return "not json at all"

    metrics = measure_judge(client=_GarbageClient())

    assert metrics.undetermined == len(JUDGE_FIXTURES)
    assert metrics.correct == 0
    assert all(isinstance(m.reason, str) for m in metrics.misses)
