"""Record a Launch Eval suite live through OpenRouter/DeepSeek (ADR-0009, ADR-0121).

This is the runnable entrypoint behind "record + replay to make the eval behaviorally
green". It loads the gitignored OpenRouter secret, builds the default record run
(:func:`hermes_runtime.eval_record.make_openrouter_record_run`, pinned primary model
``deepseek/deepseek-v4-pro``), records every scenario in the suite through the real
``AIAgent`` loop + the scenario's governed mocks/gate/identity, and persists one
transcript per scenario for deterministic ``--harness replay``.

Run from the repo root::

    uv --project hermes-runtime run python -m hermes_runtime.record_eval \\
        --suite text_first_launch

Secrets come from ``hermes-runtime/.env`` (gitignored) or the process environment;
the run fails closed if ``OPENROUTER_API_KEY`` is absent.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from toee_hermes.persona import EXTERNAL_CUSTOMER_SERVICE_PERSONA

from hermes_runtime.eval_record import (
    RecordedScenario,
    make_openrouter_record_run,
    record_suite,
)

# Repo root is two levels up from this file: <root>/hermes-runtime/hermes_runtime/.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_EVAL_DIR = _REPO_ROOT / "eval"
_DEFAULT_TRANSCRIPTS_DIR = _DEFAULT_EVAL_DIR / "transcripts"
_DEFAULT_ENV_FILE = _REPO_ROOT / "hermes-runtime" / ".env"


def load_env_file(path: Path) -> dict[str, str]:
    """Load ``KEY=VALUE`` lines from ``path`` into ``os.environ`` (absent keys only).

    A pragmatic dotenv loader so the gitignored OpenRouter secret never lands in the
    repo. Blank lines and ``#`` comments are skipped; surrounding quotes are stripped.
    An already-set environment variable is never overwritten (the process env wins, so
    a one-off ``OPENROUTER_MODEL=... uv run ...`` overrides the file). Returns the
    parsed mapping. A missing file is not an error (env may be set another way).
    """
    if not path.is_file():
        return {}
    parsed: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        parsed[key] = value
        os.environ.setdefault(key, value)
    return parsed


def _print_progress(entry: RecordedScenario) -> None:
    tools = ", ".join(f"{c.tool}.{c.action}{'' if c.ok else '!'}" for c in entry.result.tool_calls)
    text = (entry.result.outbound_text or "").replace("\n", " ")
    if len(text) > 80:
        text = text[:77] + "..."
    sys.stdout.write(
        f"  [{entry.scenario_id}] tools=[{tools}] case={entry.result.case_created} "
        f"text={text!r}\n"
    )
    sys.stdout.flush()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Record a Launch Eval suite live via OpenRouter.")
    parser.add_argument("--suite", default="text_first_launch", help="Suite to record.")
    parser.add_argument("--eval-dir", type=Path, default=_DEFAULT_EVAL_DIR)
    parser.add_argument("--transcripts-dir", type=Path, default=_DEFAULT_TRANSCRIPTS_DIR)
    parser.add_argument("--env-file", type=Path, default=_DEFAULT_ENV_FILE)
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=12,
        help="Agent loop cap per turn (tool iterations + final reply).",
    )
    parser.add_argument(
        "--scenarios",
        default=None,
        help="Comma-separated scenario ids to record (default: the whole suite).",
    )
    args = parser.parse_args(argv)

    scenario_ids = (
        [s.strip() for s in args.scenarios.split(",") if s.strip()]
        if args.scenarios
        else None
    )

    load_env_file(args.env_file)

    run_turn = make_openrouter_record_run(max_iterations=args.max_iterations)

    sys.stdout.write(
        f"Recording suite {args.suite!r} -> {args.transcripts_dir} "
        f"(model={os.environ.get('OPENROUTER_MODEL', 'deepseek/deepseek-v4-pro')})\n"
    )
    sys.stdout.flush()

    recorded = record_suite(
        args.suite,
        eval_dir=args.eval_dir,
        transcripts_dir=args.transcripts_dir,
        run_turn=run_turn,
        system_message=EXTERNAL_CUSTOMER_SERVICE_PERSONA,
        scenario_ids=scenario_ids,
        on_scenario=_print_progress,
    )

    sys.stdout.write(f"Recorded {len(recorded)} scenario(s) to {args.transcripts_dir}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI shell
    raise SystemExit(main())
