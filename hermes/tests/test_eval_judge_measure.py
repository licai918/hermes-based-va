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
from eval_runner.judge_measure import measure_judge, measure_judge_legs


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


# ---------------------------------------------------------------------------
# S21 (0.0.5 FR-28): per-leg precision/recall
# ---------------------------------------------------------------------------


def test_per_leg_metrics_cover_every_leg_and_partition_the_fixture_set() -> None:
    # The whole-set number hides a bad leg: a leg that never fires and a leg
    # that fires on everything can average out to a respectable headline.
    overall, by_leg = measure_judge_legs(client=_PerfectJudgeClient(JUDGE_FIXTURES))

    assert set(by_leg) == {f.leg for f in JUDGE_FIXTURES}
    assert sum(m.total for m in by_leg.values()) == len(JUDGE_FIXTURES)
    assert overall.total == len(JUDGE_FIXTURES)
    assert overall.correct == len(JUDGE_FIXTURES)
    for leg, metrics in by_leg.items():
        assert metrics.precision == 1.0, leg
        assert metrics.recall == 1.0, leg


def test_per_leg_metrics_localize_a_bad_leg() -> None:
    # A client that is perfect everywhere except the safety leg must show a
    # damaged safety leg and untouched siblings -- the whole point of splitting.
    class _BlindOnSafety:
        def __init__(self) -> None:
            self._by_reply = {f.reply: f for f in JUDGE_FIXTURES}

        def complete(self, prompt: str, *, model: str) -> str:
            for reply, fixture in self._by_reply.items():
                if reply in prompt:
                    expected = (
                        True
                        if fixture.leg == "injection_resisted"
                        else fixture.expected_passed
                    )
                    return f'{{"verdict": "{"yes" if expected else "no"}", "reason": "x"}}'
            raise AssertionError("prompt did not contain a known fixture reply")

    _overall, by_leg = measure_judge_legs(client=_BlindOnSafety())

    assert by_leg["injection_resisted"].precision < 1.0
    for leg, metrics in by_leg.items():
        if leg != "injection_resisted":
            assert metrics.precision == 1.0 and metrics.recall == 1.0, leg


def test_each_fixture_is_judged_exactly_once_across_the_legs() -> None:
    # One pass, not one pass per leg: --live measurement is billed per call.
    class _CountingClient:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, prompt: str, *, model: str) -> str:
            self.calls += 1
            return '{"verdict": "yes", "reason": "x"}'

    client = _CountingClient()
    measure_judge_legs(client=client)

    assert client.calls == len(JUDGE_FIXTURES)


def test_the_held_out_split_partitions_the_set_so_it_costs_no_extra_calls() -> None:
    # S21 review: measuring in-sample and held-out separately must not double
    # the billed calls -- the subsets partition, so every fixture is judged once.
    from eval_runner.judge_measure import split_held_out

    in_sample, held_out = split_held_out()

    assert in_sample and held_out
    assert len(in_sample) + len(held_out) == len(JUDGE_FIXTURES)
    assert not {f.name for f in in_sample} & {f.name for f in held_out}
    assert all(not f.held_out for f in in_sample)
    assert all(f.held_out for f in held_out)


def test_the_never_scored_live_note_names_fixtures_that_still_exist() -> None:
    # S21 verification: the `--live` run prints which held-out fixtures carry no
    # live evidence yet. A note naming a renamed or deleted fixture is worse than
    # none -- it reads as a caveat about something that is no longer there.
    from eval_runner.judge_measure import UNSCORED_LIVE_FIXTURES

    known = {f.name for f in JUDGE_FIXTURES}
    assert set(UNSCORED_LIVE_FIXTURES) <= known, (
        f"{sorted(set(UNSCORED_LIVE_FIXTURES) - known)} no longer exist; either "
        "fix the names or, if they have been scored live, delete the note"
    )
    assert all(f.held_out for f in JUDGE_FIXTURES if f.name in UNSCORED_LIVE_FIXTURES)


def test_cli_main_default_fake_path_prints_a_summary_and_exits_zero(capsys) -> None:
    """The repeatable command (PRD FR-29 acceptance layer 1): `python -m
    eval_runner.judge_measure` with no flags -- CI-safe (no network), deterministic
    oracle client, must exit 0 and print a precision/recall summary line."""
    from eval_runner.judge_measure import main

    exit_code = main([])

    from eval_runner.judge_measure import split_held_out

    out = capsys.readouterr().out
    assert exit_code == 0
    # S21 review: reported as two runs, never one averaged number -- the
    # in-sample fixtures are the ones the rubric guidance was tuned against.
    in_sample, held_out = split_held_out()
    assert f"judge_measure [in-sample]: total={len(in_sample)}" in out
    assert f"judge_measure [held-out]: total={len(held_out)}" in out
    assert len(in_sample) + len(held_out) == len(JUDGE_FIXTURES)
    assert "precision=1.000" in out
    assert "recall=1.000" in out
    assert "MISS" not in out  # oracle client scores its own labels perfectly
    # S21: the per-leg breakdown is the calibration output, not a footnote.
    for leg in {f.leg for f in JUDGE_FIXTURES}:
        assert f"leg={leg}" in out
