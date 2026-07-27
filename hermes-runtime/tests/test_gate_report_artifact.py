"""The gate-report artifact writer (S23, FR-32) is best-effort: an unwritable reports
dir must NEVER raise -- it logs and returns None so a gate/judge exit code is untouched.
"""

from __future__ import annotations

from pathlib import Path

from hermes_runtime.gate_report_artifact import write_report

_ROWS = [{"name": "n", "command": "c", "result": "r", "passed": True, "note": None}]


def test_write_report_round_trips_to_a_writable_dir(tmp_path: Path) -> None:
    path = write_report("recall", "src", _ROWS, reports_dir=tmp_path)
    assert path is not None and path.exists()


def test_write_report_returns_none_and_never_raises_on_an_unwritable_dir(tmp_path: Path, capsys) -> None:
    # A file where a directory is expected -> mkdir(parents=True) raises OSError.
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a dir", encoding="utf-8")

    result = write_report("recall", "src", _ROWS, reports_dir=blocker / "sub")

    assert result is None  # swallowed, not raised
    assert "could not write gate report artifact" in capsys.readouterr().err
