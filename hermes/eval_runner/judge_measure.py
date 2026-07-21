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

from .judge import JudgeClient, judge_reply, resolve_judge_model
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

    metrics = measure_judge(JUDGE_FIXTURES, client=client, model=model)

    print(
        f"judge_measure: total={metrics.total} correct={metrics.correct} "
        f"precision={metrics.precision:.3f} recall={metrics.recall:.3f} "
        f"accuracy={metrics.accuracy:.3f} undetermined={metrics.undetermined}"
    )
    for miss in metrics.misses:
        print(
            f"  MISS leg={miss.fixture.leg} expected={miss.fixture.expected_passed} "
            f"got={miss.got_passed}: {miss.reason}"
        )

    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI shell
    raise SystemExit(main())
