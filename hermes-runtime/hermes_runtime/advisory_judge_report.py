"""Advisory live-model judge run -> PR markdown, every PR (S20, FR-28/FR-29, NFR-7).

The runnable the advisory CI job invokes. It runs the S27-tuned judge (real OpenRouter
model, :func:`eval_runner.judge.resolve_judge_model`) over the labelled scenario set
(:data:`eval_runner.judge_fixtures.JUDGE_FIXTURES`) and renders the advisory report
(:mod:`eval_runner.judge_report`) as a file the CI job uploads as an artifact and
upserts into one PR comment.

Advisory means advisory (FR-29): a "no"/undetermined verdict is the thing this tool
exists to surface, not a failure -- it exits 0 on judge misses and flakes alike. The
ONLY non-zero exit is a genuine "could not run at all" infra fault. It never gates
merge and is deliberately not in any required-status set (NFR-7); the required wall
stays the scripted replay gate.

Owner-key handling: when ``OPENROUTER_API_KEY`` is absent the job SKIPS gracefully --
it writes the skipped report and exits 0, never failing a PR. The moment the owner adds
the repo secret the same job lights up with a real measurement, no code change.

Run from the repo root::

    uv --project hermes-runtime run python -m hermes_runtime.advisory_judge_report \\
        --out advisory-judge-report.md

Secrets come from ``hermes-runtime/.env`` (gitignored) or the process environment, the
same loader ``record_eval`` / ``judge_eval`` use.
"""

from __future__ import annotations

import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional

from eval_runner.judge import JudgeClient, resolve_judge_model
from eval_runner.judge_measure import measure_judge
from eval_runner.judge_report import render_report, render_skipped

from hermes_runtime.gate_report_artifact import write_report
from hermes_runtime.openrouter import openrouter_configured, resolve_openrouter_config
from hermes_runtime.record_eval import load_env_file

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_ENV_FILE = _REPO_ROOT / "hermes-runtime" / ".env"
_DEFAULT_OUT = _REPO_ROOT / "advisory-judge-report.md"

_SKIP_REASON = "advisory judge skipped — OPENROUTER_API_KEY not configured"


def _build_live_client() -> JudgeClient:
    """Construct the real OpenRouter-backed judge client (only when a key is present)."""
    from hermes_runtime.judge_eval import OpenRouterJudgeClient

    config = resolve_openrouter_config()
    return OpenRouterJudgeClient(base_url=config.base_url, api_key=config.api_key)


def _emit(out: Path, markdown: str) -> None:
    out.write_text(markdown, encoding="utf-8")
    sys.stdout.write(markdown)
    if not markdown.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()


def main(argv: Optional[list[str]] = None, *, client: Optional[JudgeClient] = None) -> int:
    parser = ArgumentParser(
        description="Advisory live-model judge run -> PR markdown (never gates CI)."
    )
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="Markdown output path.")
    parser.add_argument("--env-file", type=Path, default=_DEFAULT_ENV_FILE)
    args = parser.parse_args(argv)

    load_env_file(args.env_file)

    # Graceful skip: no owner key -> write the skipped report, exit 0, never block.
    if client is None and not openrouter_configured():
        _emit(args.out, render_skipped(_SKIP_REASON))
        return 0

    judge = client if client is not None else _build_live_client()
    model = resolve_judge_model()
    metrics = measure_judge(client=judge, model=model)
    _emit(args.out, render_report(metrics, model=model))

    # Emit the live artifact the QualityGatesPanel reads (S23, FR-32). Only on a
    # REAL measurement -- the graceful skip above writes nothing, so the panel
    # honestly shows no judge report rather than a fabricated one. `passed=None`:
    # advisory forever (FR-29/NFR-7), never a PASS/FAIL gate.
    write_report(
        "judge",
        "python -m hermes_runtime.advisory_judge_report",
        [
            {
                "name": "Judge precision/recall (FR-29)",
                "command": "python -m hermes_runtime.advisory_judge_report",
                "result": (
                    f"precision {metrics.precision:.3f}, recall {metrics.recall:.3f}, "
                    f"accuracy {metrics.accuracy:.3f} ({metrics.total} fixtures, "
                    f"{metrics.undetermined} undetermined)"
                ),
                "passed": None,
                "note": f"Judge model {model}. Advisory only -- never blocks merge (NFR-7).",
            }
        ],
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI shell
    raise SystemExit(main())
