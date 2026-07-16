"""Advisory-judge already-recorded Launch Eval transcripts (S08, ADR-0009, ADR-0121).

The honored / no_unprompted_recall signal is advisory only (PRD workspace/0.0.2/PRD.md
§9 decision 4): it is never allowed inside the deterministic ``--harness replay`` gate
(see ``hermes/tests/test_eval_advisory.py``'s gate-boundary sweep), so it gets its own
tiny runnable entrypoint here, the judging twin of ``hermes_runtime.record_eval`` /
``hermes_runtime.record_copilot_eval``'s "the runnable entrypoint behind X" shape.

Reads each named scenario's transcript already on disk (``eval/transcripts/<suite>/
<id>.json``, written by ``record_eval`` / ``record_copilot_eval``), judges it via a
live OpenRouter-backed client on the S06 cheap model, and prints the verdict. There is
no "which leg does this scenario want" auto-detection (mirrors ``record_copilot_eval``'s
own explicit-``--scenarios`` precedent -- no per-scenario flag exists to guess from, so
the caller names both the scenarios and the leg). Exit code is always 0 for a verdict
outcome: a "no"/"undetermined" verdict is not this tool's failure, it is the thing the
tool exists to surface.

Run from the repo root::

    uv --project hermes-runtime run python -m hermes_runtime.judge_eval \\
        --suite text_first_launch --scenarios 25,27,28 --leg honored
    uv --project hermes-runtime run python -m hermes_runtime.judge_eval \\
        --suite text_first_launch --scenarios 31 --leg no_unprompted_recall

Secrets come from ``hermes-runtime/.env`` (gitignored) or the process environment,
the same loader ``record_eval`` uses (fails closed if ``OPENROUTER_API_KEY`` is absent).
"""

from __future__ import annotations

import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional

from eval_runner.advisory import judge_scenario_leg
from eval_runner.fixtures import load_scenario
from eval_runner.judge import DEFAULT_JUDGE_MODEL, JudgeVerdict
from eval_runner.replay import ReplayAgentHarness

from hermes_runtime.openrouter import resolve_openrouter_config
from hermes_runtime.record_eval import load_env_file

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_EVAL_DIR = _REPO_ROOT / "eval"
_DEFAULT_TRANSCRIPTS_DIR = _DEFAULT_EVAL_DIR / "transcripts"
_DEFAULT_ENV_FILE = _REPO_ROOT / "hermes-runtime" / ".env"

_LEG_VALUES = ("honored", "no_unprompted_recall")


class OpenRouterJudgeClient:
    """Live ``eval_runner.judge.JudgeClient`` over OpenRouter's chat endpoint.

    One plain completion, no tools, no agent loop -- the judge only ever needs a
    single ``complete(prompt, model=...) -> str`` call, unlike the full AIAgent turn
    ``hermes_runtime.live.run_agent_turn`` drives for a real conversation.
    ``openai_factory`` injects a fake client in tests (mirrors every other
    OpenRouter seam in this package, e.g. ``make_openrouter_record_run``); the real
    ``openai.OpenAI`` is used otherwise.
    """

    def __init__(
        self, *, base_url: str, api_key: str, openai_factory: Any = None
    ) -> None:
        factory = openai_factory
        if factory is None:
            from openai import OpenAI

            factory = OpenAI
        self._client = factory(base_url=base_url, api_key=api_key)

    def complete(self, prompt: str, *, model: str) -> str:
        response = self._client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content or ""


def _print_verdict(scenario_id: str, leg: str, verdict: JudgeVerdict) -> None:
    sys.stdout.write(
        f"  [{scenario_id}] leg={leg} passed={verdict.passed} reason={verdict.reason!r}\n"
    )
    sys.stdout.flush()


def main(argv: Optional[list[str]] = None) -> int:
    parser = ArgumentParser(
        description="Advisory-judge already-recorded Launch Eval transcripts (never gates CI)."
    )
    parser.add_argument("--suite", default="text_first_launch", help="Suite the scenario ids belong to.")
    parser.add_argument("--eval-dir", type=Path, default=_DEFAULT_EVAL_DIR)
    parser.add_argument("--transcripts-dir", type=Path, default=_DEFAULT_TRANSCRIPTS_DIR)
    parser.add_argument("--env-file", type=Path, default=_DEFAULT_ENV_FILE)
    parser.add_argument(
        "--leg", required=True, choices=_LEG_VALUES, help="Which advisory leg to judge."
    )
    parser.add_argument(
        "--scenarios", required=True, help="Comma-separated scenario ids to judge (e.g. 25,27,28)."
    )
    parser.add_argument("--model", default=DEFAULT_JUDGE_MODEL)
    args = parser.parse_args(argv)

    load_env_file(args.env_file)
    config = resolve_openrouter_config()
    client = OpenRouterJudgeClient(base_url=config.base_url, api_key=config.api_key)

    harness = ReplayAgentHarness(args.transcripts_dir)
    scenario_ids = [s.strip() for s in args.scenarios.split(",") if s.strip()]

    sys.stdout.write(
        f"Advisory-judging leg={args.leg!r} scenarios={scenario_ids} (model={args.model})\n"
    )
    sys.stdout.flush()

    for scenario_id in scenario_ids:
        scenario = load_scenario(args.suite, scenario_id, args.eval_dir)
        result = harness.run_turn(scenario)
        verdict = judge_scenario_leg(
            scenario, result, leg=args.leg, client=client, model=args.model
        )
        _print_verdict(scenario.scenario_id, args.leg, verdict)

    sys.stdout.write("Advisory only -- this signal never gates CI (PRD §9 decision 4).\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI shell
    raise SystemExit(main())
