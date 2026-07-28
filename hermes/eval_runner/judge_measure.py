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

The fixture set spans several legs, each with its own "positive" meaning
(``honored`` / ``silent`` / ``not misapplied`` / ``current value`` / ``resisted``).
Precision/recall here treat ``expected_passed=True`` as the positive class
uniformly across every leg -- which is why the leg names are all phrased so that
True means "the agent behaved well" (see :data:`eval_runner.judge.JudgeLeg`).

S21 (0.0.5 FR-28) adds :func:`measure_judge_legs`: the same measurement split PER
LEG. The whole-set number is the headline, but it is the per-leg numbers that
say whether a given advisory leg is trustworthy enough to report -- an average
happily hides a leg that fires on everything next to one that never fires.

CLI (repeatable command, PRD FR-29 acceptance layer 1)::

    python -m eval_runner.judge_measure           # default: deterministic oracle
                                                    # fake, CI-safe, no network
    python -m eval_runner.judge_measure --live     # real judge model over
                                                    # OpenRouter -- costs one API
                                                    # call, requires
                                                    # OPENROUTER_API_KEY (via
                                                    # hermes-runtime/.env or the
                                                    # environment); manual-only,
                                                    # never run in CI
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional, Sequence

from .judge import (
    JudgeClient,
    judge_reply,
    legs_with_guidance,
    resolve_judge_model,
)
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


def split_held_out(
    fixtures: Sequence[JudgeFixture] = JUDGE_FIXTURES,
) -> tuple[tuple[JudgeFixture, ...], tuple[JudgeFixture, ...]]:
    """``(in_sample, held_out)`` -- the contamination split (S21 review).

    :data:`eval_runner.judge._LEG_GUIDANCE` was written against the in-sample
    fixtures (its verb list, its "merely mentioning" carve-out, and a memory
    rendering it quotes verbatim all map onto specific ones), so an in-sample
    precision of 1.000 partly measures the prompt describing those fixtures. The
    held-out fixtures use shapes the guidance never mentions; they are scored and
    reported on their own, never averaged into the in-sample figure.

    The two subsets PARTITION the set, so measuring both costs exactly what
    measuring the whole set once costs -- one billed completion per fixture.
    """
    return (
        tuple(f for f in fixtures if not f.held_out),
        tuple(f for f in fixtures if f.held_out),
    )


def held_out_effective_n_note(
    fixtures: Sequence[JudgeFixture] = JUDGE_FIXTURES,
) -> str:
    """State the EFFECTIVE held-out n, not the headcount (S21 re-review).

    "Held out from the rubric guidance" only means something on a leg that HAS
    leg-specific guidance (:func:`eval_runner.judge.legs_with_guidance`). The
    others get the shared preamble only, so their held-out fixtures are held out
    from nothing and are not evidence about contamination -- reporting the
    headcount as the strength of the split overstates it.

    One sentence, generated rather than written down, because the requirement is
    that the caveat travels with the number EVERYWHERE the number appears: this
    CLI, the PR markdown (``judge_report``) and the quality-gates panel row
    (``hermes_runtime.advisory_judge_report``) all print this exact string.
    """
    guided = set(legs_with_guidance())
    held_out = [f for f in fixtures if f.held_out]
    effective = [f for f in held_out if f.leg in guided]
    unguided = sorted({f.leg for f in held_out} - guided)
    if not unguided:
        return f"Effective held-out n: **{len(effective)} of {len(held_out)}**."
    names = ", ".join(f"`{leg}`" for leg in unguided)
    return (
        f"**Effective held-out n is {len(effective)} of {len(held_out)}.** Only "
        f"{len(guided & {f.leg for f in held_out})} legs carry leg-specific "
        f"rubric guidance to be held out FROM; {names} get the shared preamble "
        "only, so their held-out fixtures are held out from nothing and say "
        "nothing about contamination. Read the per-leg rows, not the total."
    )


def _combine(parts: Sequence[JudgeMetrics]) -> JudgeMetrics:
    """Sum per-leg metrics into the whole-set metrics.

    Legs PARTITION the fixture set, so the sum is exactly what
    :func:`measure_judge` would have returned over all of them -- without paying
    for a second (billed, on ``--live``) pass.
    """
    return JudgeMetrics(
        total=sum(p.total for p in parts),
        correct=sum(p.correct for p in parts),
        true_positives=sum(p.true_positives for p in parts),
        false_positives=sum(p.false_positives for p in parts),
        true_negatives=sum(p.true_negatives for p in parts),
        false_negatives=sum(p.false_negatives for p in parts),
        undetermined=sum(p.undetermined for p in parts),
        misses=tuple(miss for p in parts for miss in p.misses),
    )


def measure_judge_legs(
    fixtures: Sequence[JudgeFixture] = JUDGE_FIXTURES,
    *,
    client: JudgeClient,
    model: Optional[str] = None,
) -> tuple[JudgeMetrics, dict[str, JudgeMetrics]]:
    """``(overall, {leg: metrics})`` -- per-leg precision/recall in ONE pass.

    S21 (0.0.5 FR-28): the whole-set number hides a bad leg. A leg that never
    fires and a leg that fires on everything average out to a respectable
    headline, and an advisory leg nobody trusts is worse than no leg -- so each
    leg is scored against its own fixtures and reported on its own row. Each
    fixture is still judged exactly once (the legs partition the set).
    """
    by_leg: dict[str, list[JudgeFixture]] = {}
    for fixture in fixtures:
        by_leg.setdefault(fixture.leg, []).append(fixture)
    metrics = {
        leg: measure_judge(leg_fixtures, client=client, model=model)
        for leg, leg_fixtures in by_leg.items()
    }
    return _combine(list(metrics.values())), metrics


class _OracleJudgeClient:
    """Deterministic stand-in that always answers a fixture's own ground truth.

    The CLI's default, CI-safe ``client`` -- no network, no API key. It does not
    measure a real judge model; it proves the ``measure_judge`` plumbing itself
    runs end-to-end (an oracle must score 100%), the same role
    ``test_eval_judge_measure.py``'s ``_PerfectJudgeClient`` plays in tests.
    """

    def __init__(self, fixtures: Sequence[JudgeFixture]) -> None:
        self._by_reply = {f.reply: f.expected_passed for f in fixtures}

    def complete(self, prompt: str, *, model: str) -> str:
        for reply, expected in self._by_reply.items():
            if reply in prompt:
                token = "yes" if expected else "no"
                return f'{{"verdict": "{token}", "reason": "oracle"}}'
        return '{"verdict": "undetermined", "reason": "unknown fixture"}'


def _build_live_client() -> JudgeClient:
    """Construct the real OpenRouter-backed judge client (``--live`` only).

    Imported lazily, inside this function, so ``eval_runner`` stays
    dependency-free (``hermes/pyproject.toml``) at module load time -- these
    names (``openai``, ``hermes_runtime``) only need to resolve when a caller
    explicitly asks for a live run.
    """
    from pathlib import Path

    from hermes_runtime.judge_eval import OpenRouterJudgeClient
    from hermes_runtime.openrouter import resolve_openrouter_config
    from hermes_runtime.record_eval import load_env_file

    repo_root = Path(__file__).resolve().parents[2]
    load_env_file(repo_root / "hermes-runtime" / ".env")
    config = resolve_openrouter_config()
    return OpenRouterJudgeClient(base_url=config.base_url, api_key=config.api_key)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point: score the judge against ``JUDGE_FIXTURES`` and print a summary.

    Default is the deterministic oracle fake (CI-safe, no network, always exits
    0). ``--live`` swaps in a real OpenRouter-backed client on the resolved judge
    model (``EVAL_JUDGE_MODEL`` or the cheap default) -- a real, billed API call;
    manual-only, never wired into CI. Fails (exit 1) only when ``--live`` can't
    even construct a client (missing ``openai``/``hermes_runtime`` or
    ``OPENROUTER_API_KEY``), never on a low judge score -- this measurement is
    advisory (NFR-3), not a gate.
    """
    args = sys.argv[1:] if argv is None else argv
    live = "--live" in args

    if live:
        try:
            client = _build_live_client()
        except Exception as error:  # ImportError, ValueError (missing API key), etc.
            print(f"--live judge measurement unavailable: {error}", file=sys.stderr)
            return 1
        model = resolve_judge_model()
        print(
            f"Running LIVE judge measurement (model={model!r}) over OpenRouter "
            "-- this makes a real, billed API call."
        )
    else:
        client = _OracleJudgeClient(JUDGE_FIXTURES)
        model = None

    # Reported as two separate runs, never averaged (S21 review): the in-sample
    # number is measured on the fixtures the rubric guidance was tuned against,
    # the held-out number on shapes it never describes. Together they still cost
    # one completion per fixture -- the subsets partition the set.
    in_sample, held_out = split_held_out(JUDGE_FIXTURES)
    for label, subset in (("in-sample", in_sample), ("held-out", held_out)):
        if not subset:
            continue
        metrics, by_leg = measure_judge_legs(subset, client=client, model=model)
        print(
            f"judge_measure [{label}]: total={metrics.total} "
            f"correct={metrics.correct} precision={metrics.precision:.3f} "
            f"recall={metrics.recall:.3f} accuracy={metrics.accuracy:.3f} "
            f"undetermined={metrics.undetermined}"
        )
        # Per-leg is the number that decides whether a leg is trustworthy (S21).
        for leg in sorted(by_leg):
            leg_metrics = by_leg[leg]
            print(
                f"  [{label}] leg={leg} n={leg_metrics.total} "
                f"correct={leg_metrics.correct} "
                f"precision={leg_metrics.precision:.3f} "
                f"recall={leg_metrics.recall:.3f} "
                f"accuracy={leg_metrics.accuracy:.3f} "
                f"undetermined={leg_metrics.undetermined}"
            )
        for miss in metrics.misses:
            print(
                f"  [{label}] MISS leg={miss.fixture.leg} "
                f"expected={miss.fixture.expected_passed} "
                f"got={miss.got_passed}: {miss.reason}"
            )
        if label == "held-out":
            print(f"  [held-out] {held_out_effective_n_note()}")

    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI shell
    raise SystemExit(main())
