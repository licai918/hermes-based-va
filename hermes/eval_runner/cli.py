"""Launch Eval CLI (ports cli.ts, ADR-0074, ADR-0121).

Parses ``--suite`` / ``--scenario`` / ``--slot``, runs the suite, prints a
per-scenario PASS/FAIL summary, and returns the go-live exit code: non-zero when
any high-severity scenario fails so CI blocks promotion. Medium-severity failures
set ``signoff_required`` but do not block.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .fixtures import PathLike
from .harness import AgentHarness, stub_agent_harness
from .replay import ReplayAgentHarness
from .run import run_suite
from .types import SUITE_VALUES

# The eval fixtures live at the repo-root ``eval/`` directory; resolve it from the
# package location so the CLI works regardless of the current working directory
# (the package lives under ``hermes/`` in the monorepo).
_DEFAULT_EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"

# Selectable agent harnesses: ``stub`` fails closed (proves the gate); ``replay``
# runs recorded transcripts deterministically (record/replay CI path).
HARNESS_VALUES: tuple[str, ...] = ("stub", "replay")


@dataclass(frozen=True)
class CliArgs:
    suite: str = "text_first_launch"
    scenario_id: Optional[str] = None
    slot: Optional[str] = None
    harness: str = "stub"
    transcripts_dir: Optional[str] = None


def parse_args(argv: list[str]) -> CliArgs:
    suite = "text_first_launch"
    scenario_id: Optional[str] = None
    slot: Optional[str] = None
    harness = "stub"
    transcripts_dir: Optional[str] = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        if arg == "--suite":
            if nxt is None or nxt not in SUITE_VALUES:
                raise ValueError(f"--suite must be one of: {', '.join(SUITE_VALUES)}")
            suite = nxt
            i += 2
        elif arg == "--scenario":
            if nxt is None:
                raise ValueError("--scenario requires a scenario id.")
            scenario_id = nxt
            i += 2
        elif arg == "--slot":
            if nxt is None:
                raise ValueError("--slot requires a policy slot name.")
            slot = nxt
            i += 2
        elif arg == "--harness":
            if nxt is None or nxt not in HARNESS_VALUES:
                raise ValueError(
                    f"--harness must be one of: {', '.join(HARNESS_VALUES)}"
                )
            harness = nxt
            i += 2
        elif arg == "--transcripts-dir":
            if nxt is None:
                raise ValueError("--transcripts-dir requires a path.")
            transcripts_dir = nxt
            i += 2
        else:
            raise ValueError(f'Unknown argument "{arg}".')

    if harness == "replay" and transcripts_dir is None:
        raise ValueError("--harness replay requires --transcripts-dir.")

    return CliArgs(
        suite=suite,
        scenario_id=scenario_id,
        slot=slot,
        harness=harness,
        transcripts_dir=transcripts_dir,
    )


def build_agent(args: CliArgs) -> AgentHarness:
    """Construct the agent harness selected by the CLI args.

    ``stub`` fails closed so the go-live gate is provable before live behavior
    exists; ``replay`` runs recorded transcripts deterministically (ADR-0121).
    """
    if args.harness == "replay":
        if args.transcripts_dir is None:
            raise ValueError("--harness replay requires --transcripts-dir.")
        return ReplayAgentHarness(args.transcripts_dir)
    return stub_agent_harness


def main(
    argv: list[str],
    *,
    eval_dir: Optional[PathLike] = None,
    write: bool = True,
) -> int:
    args = parse_args(argv)
    target_dir: PathLike = eval_dir if eval_dir is not None else _DEFAULT_EVAL_DIR

    result = run_suite(
        suite=args.suite,
        eval_dir=target_dir,
        scenario_id=args.scenario_id,
        slot=args.slot,
        agent=build_agent(args),
        write=write,
    )
    report = result.report
    summary = report.summary

    for scenario in report.scenarios:
        status = "PASS" if scenario.passed else f"FAIL [{scenario.severity}]"
        print(f"{status}  {scenario.scenario_id}  {scenario.title}")
        for failure in scenario.failed_assertions:
            print(f"        - {failure.type}/{failure.name}: {failure.detail}")

    print(
        f"\n{report.suite}: {summary.passed}/{summary.total} passed | "
        f"failed_high={summary.failed_high} failed_medium={summary.failed_medium}"
    )
    if result.report_path is not None:
        print(f"Report: {result.report_path}")
    if report.signoff_required:
        print("Medium-severity failures require sign_off_medium_failure.")

    # Go-live gate (ADR-0074, ADR-0121): high-severity failures block promotion.
    return 1 if summary.failed_high > 0 else 0


def _entrypoint() -> int:
    try:
        return main(sys.argv[1:])
    except Exception as error:  # noqa: BLE001 - top-level CLI guard
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_entrypoint())
