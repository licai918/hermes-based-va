"""The S20 advisory judge runnable: graceful key-skip + rendered report (FR-28/29, NFR-7).

No network, no real ``OPENROUTER_API_KEY``. Two paths matter and both are here:

* key ABSENT -> the job skips gracefully (skipped report, exit 0, never blocks);
* key PRESENT -> a real measurement renders the full advisory report. The live model
  itself is owner-key-gated and untestable here, so the "present" path is exercised
  with an INJECTED fake judge client -- the same mock-judge substitution the renderer's
  own unit tests use.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hermes_runtime.advisory_judge_report import main


@pytest.fixture(autouse=True)
def _isolate_gate_reports(tmp_path_factory, monkeypatch):
    # A real measurement now emits a live judge artifact (S23); keep it out of the
    # repo's real .reports/gates during tests.
    monkeypatch.setenv("GATE_REPORTS_DIR", str(tmp_path_factory.mktemp("gate-reports")))


class _AlwaysYesJudge:
    def complete(self, prompt: str, *, model: str) -> str:
        return '{"verdict": "yes", "reason": "mock"}'


def test_skips_gracefully_without_a_key(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    out = tmp_path / "report.md"

    # env-file points at a nonexistent path so no local .env supplies a key.
    exit_code = main(["--out", str(out), "--env-file", str(tmp_path / "absent.env")])

    assert exit_code == 0
    body = out.read_text(encoding="utf-8")
    assert "Skipped:" in body
    assert "OPENROUTER_API_KEY" in body
    assert "never blocks" in body
    assert "Skipped:" in capsys.readouterr().out
    # No measurement ran -> no fabricated judge artifact for the panel (S23 honesty).
    assert list(Path(os.environ["GATE_REPORTS_DIR"]).glob("judge-*.json")) == []


def test_renders_full_report_with_an_injected_judge(tmp_path: Path, capsys) -> None:
    out = tmp_path / "report.md"

    exit_code = main(
        ["--out", str(out), "--env-file", str(tmp_path / "absent.env")],
        client=_AlwaysYesJudge(),
    )

    assert exit_code == 0
    body = out.read_text(encoding="utf-8")
    assert "Advisory only" in body
    assert "precision `" in body
    assert "| `honored` |" in body
    # Always-yes judge is wrong on the ground-truth negatives -> a misses table renders.
    assert "| Fixture | Leg |" in body
    assert "precision `" in capsys.readouterr().out
    # A real measurement emits the live judge artifact the panel reads (S23), advisory
    # (passed=None), carrying the same precision/recall numbers.
    reports = list(Path(os.environ["GATE_REPORTS_DIR"]).glob("judge-*.json"))
    assert len(reports) == 1
    art = json.loads(reports[0].read_text(encoding="utf-8"))
    assert art["kind"] == "judge"
    assert art["rows"][0]["passed"] is None
    assert "precision" in art["rows"][0]["result"]


def test_exit_zero_even_when_the_judge_is_useless(tmp_path: Path) -> None:
    class _GarbageJudge:
        def complete(self, prompt: str, *, model: str) -> str:
            return "not json"

    out = tmp_path / "report.md"
    exit_code = main(
        ["--out", str(out), "--env-file", str(tmp_path / "absent.env")],
        client=_GarbageJudge(),
    )

    # Advisory: undetermined verdicts are surfaced, never a non-zero exit (FR-29).
    assert exit_code == 0
    assert "undetermined" in out.read_text(encoding="utf-8")
