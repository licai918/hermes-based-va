"""Record Launch Eval copilot-draft scenarios live through OpenRouter (S07).

The copilot twin of :mod:`hermes_runtime.record_eval`: drives the UNBOUND
``internal_copilot`` draft seam through
:func:`hermes_runtime.copilot_eval_record.record_copilot_scenario_turn` instead of
the bound External turn, for the scenario ids named on the command line. There is
no "is this a copilot scenario" flag in the fixture format (see
``.superpowers/sdd/S05-spike-note.md``), so the caller names them explicitly rather
than this script guessing from the whole suite.

Run from the repo root::

    uv --project hermes-runtime run python -m hermes_runtime.record_copilot_eval \\
        --suite text_first_launch --scenarios 30

Secrets come from ``hermes-runtime/.env`` (gitignored) or the process environment.
Without ``OPENROUTER_API_KEY`` the turn falls back to the deterministic keyless stub
(``make_copilot_run_turn``'s Fork C1 precedence) rather than failing closed -- so a
scenario meant for a live recording will visibly record a stub-labelled transcript
if the key is missing, rather than erroring.

This script FORCES ``INTEGRATION_DRIVER=mock`` and ``TOOL_BACKEND=mock`` after
loading the env file, regardless of what it (or the ambient shell) set. The External
recorder never has this problem: ``boot_profile_eval`` injects the scenario's
MockDriver directly, so ``INTEGRATION_DRIVER`` is never consulted (S05 spike). The
copilot boot path (plain ``register()``) has no such injection seam, so it falls
through to env resolution -- and a dev ``.env`` configured for real end-to-end runs
(``INTEGRATION_DRIVER=composio``, ``TOOL_BACKEND=datastore``) will otherwise send a
"recording" against the REAL Shopify/EasyRoutes/Postgres backends (confirmed while
recording scenario 30: an unforced run leaked real store catalog data into the
transcript). Launch Eval recordings are mock-backed by convention (ADR-0071); this
keeps the copilot path on that convention rather than a per-run flag.
"""

from __future__ import annotations

import os
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Optional

from eval_runner.fixtures import load_scenario

from hermes_runtime.copilot_eval_record import record_copilot_scenario_turn
from hermes_runtime.record_eval import load_env_file

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_EVAL_DIR = _REPO_ROOT / "eval"
_DEFAULT_TRANSCRIPTS_DIR = _DEFAULT_EVAL_DIR / "transcripts"
_DEFAULT_ENV_FILE = _REPO_ROOT / "hermes-runtime" / ".env"


def main(argv: Optional[list[str]] = None) -> int:
    parser = ArgumentParser(description="Record Launch Eval copilot-draft scenarios live via OpenRouter.")
    parser.add_argument("--suite", default="text_first_launch", help="Suite the scenario ids belong to.")
    parser.add_argument("--eval-dir", type=Path, default=_DEFAULT_EVAL_DIR)
    parser.add_argument("--transcripts-dir", type=Path, default=_DEFAULT_TRANSCRIPTS_DIR)
    parser.add_argument("--env-file", type=Path, default=_DEFAULT_ENV_FILE)
    parser.add_argument(
        "--channel",
        default="sms",
        help="Copilot draft channel: sms/email/internal_note/chat (default sms).",
    )
    parser.add_argument("--max-iterations", type=int, default=12)
    parser.add_argument(
        "--scenarios",
        required=True,
        help="Comma-separated copilot scenario ids to record (e.g. 30).",
    )
    args = parser.parse_args(argv)

    load_env_file(args.env_file)
    # Force mock-backed reads/writes regardless of .env (see module docstring): a
    # dev .env pointed at real Composio/Postgres would otherwise turn a "recording"
    # into a live call against real systems. Only the model boundary stays real.
    os.environ["INTEGRATION_DRIVER"] = "mock"
    os.environ["TOOL_BACKEND"] = "mock"

    scenario_ids = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    sys.stdout.write(
        f"Recording copilot scenario(s) {scenario_ids} -> {args.transcripts_dir} "
        f"(model={os.environ.get('OPENROUTER_MODEL', 'deepseek/deepseek-v4-pro')})\n"
    )
    sys.stdout.flush()

    for scenario_id in scenario_ids:
        scenario = load_scenario(args.suite, scenario_id, args.eval_dir)
        path, result = record_copilot_scenario_turn(
            scenario,
            transcripts_dir=args.transcripts_dir,
            channel=args.channel,
            max_iterations=args.max_iterations,
        )
        tools = ", ".join(f"{c.tool}.{c.action}{'' if c.ok else '!'}" for c in result.tool_calls)
        text = (result.outbound_text or "").replace("\n", " ")
        if len(text) > 80:
            text = text[:77] + "..."
        sys.stdout.write(f"  [{scenario.scenario_id}] -> {path} tools=[{tools}] text={text!r}\n")
        sys.stdout.flush()

    sys.stdout.write(f"Recorded {len(scenario_ids)} copilot scenario(s) to {args.transcripts_dir}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI shell
    raise SystemExit(main())
