"""Tests for the Launch Eval CLI (ports cli.ts, ADR-0074, ADR-0121).

``parse_args`` validates suite/scenario/slot flags; ``main`` runs the suite and
returns the go-live exit code: non-zero when any high-severity scenario fails so
CI blocks promotion. The stub harness fails high scenarios, so a high scenario
exits non-zero while a medium-only failure still exits zero.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval_runner.cli import CliArgs, build_agent, main, parse_args
from eval_runner.harness import stub_agent_harness
from eval_runner.replay import ReplayAgentHarness

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


def test_parse_args_defaults_to_text_first_launch() -> None:
    assert parse_args([]) == CliArgs(suite="text_first_launch")


def test_parse_args_reads_suite_scenario_and_slot() -> None:
    assert parse_args(["--suite", "email_go_live"]) == CliArgs(suite="email_go_live")
    assert parse_args(["--scenario", "01"]) == CliArgs(
        suite="text_first_launch", scenario_id="01"
    )
    assert parse_args(["--suite", "policy_publish", "--slot", "x"]) == CliArgs(
        suite="policy_publish", slot="x"
    )


def test_parse_args_rejects_unknown_suite() -> None:
    with pytest.raises(ValueError, match="--suite"):
        parse_args(["--suite", "nope"])


def test_parse_args_rejects_unknown_argument() -> None:
    with pytest.raises(ValueError, match="Unknown argument"):
        parse_args(["--bogus"])


def test_parse_args_rejects_flags_without_values() -> None:
    with pytest.raises(ValueError, match="--scenario"):
        parse_args(["--scenario"])
    with pytest.raises(ValueError, match="--slot"):
        parse_args(["--slot"])


def test_parse_args_defaults_harness_to_stub() -> None:
    args = parse_args([])
    assert args.harness == "stub"
    assert args.transcripts_dir is None


def test_parse_args_reads_harness_and_transcripts_dir() -> None:
    args = parse_args(["--harness", "replay", "--transcripts-dir", "eval/transcripts"])
    assert args.harness == "replay"
    assert args.transcripts_dir == "eval/transcripts"


def test_parse_args_rejects_unknown_harness() -> None:
    with pytest.raises(ValueError, match="--harness"):
        parse_args(["--harness", "live"])


def test_parse_args_replay_requires_transcripts_dir() -> None:
    with pytest.raises(ValueError, match="transcripts-dir"):
        parse_args(["--harness", "replay"])


def test_build_agent_defaults_to_stub() -> None:
    assert build_agent(parse_args([])) is stub_agent_harness


def test_build_agent_returns_replay_harness_for_replay() -> None:
    agent = build_agent(
        parse_args(["--harness", "replay", "--transcripts-dir", "eval/transcripts"])
    )
    assert isinstance(agent, ReplayAgentHarness)
    assert agent.transcripts_dir == Path("eval/transcripts")


def test_main_exits_nonzero_when_high_severity_scenario_fails() -> None:
    # Scenario 04 is high severity; the default stub harness fails it -> gate blocks.
    code = main(["--suite", "text_first_launch", "--scenario", "04"], eval_dir=EVAL_DIR, write=False)
    assert code == 1


def test_main_exits_zero_when_only_medium_severity_fails() -> None:
    # Scenario 01 is medium; the stub fails it but the high-severity gate is clean.
    code = main(["--suite", "text_first_launch", "--scenario", "01"], eval_dir=EVAL_DIR, write=False)
    assert code == 0
