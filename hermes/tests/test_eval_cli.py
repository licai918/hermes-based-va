"""Tests for the Launch Eval CLI (ports cli.ts, ADR-0074, ADR-0121).

``parse_args`` validates suite/scenario/slot flags; ``main`` runs the suite and
returns the go-live exit code: non-zero when any high-severity scenario fails so
CI blocks promotion. The stub harness fails high scenarios, so a high scenario
exits non-zero while a medium-only failure still exits zero.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval_runner.cli import CliArgs, main, parse_args

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


def test_main_exits_nonzero_when_high_severity_scenario_fails() -> None:
    # Scenario 04 is high severity; the default stub harness fails it -> gate blocks.
    code = main(["--suite", "text_first_launch", "--scenario", "04"], eval_dir=EVAL_DIR, write=False)
    assert code == 1


def test_main_exits_zero_when_only_medium_severity_fails() -> None:
    # Scenario 01 is medium; the stub fails it but the high-severity gate is clean.
    code = main(["--suite", "text_first_launch", "--scenario", "01"], eval_dir=EVAL_DIR, write=False)
    assert code == 0
