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


def test_panel_rows_label_their_split_and_carry_the_effective_held_out_n(
    tmp_path: Path,
) -> None:
    # S21 re-review: the per-leg panel rows were measured on the IN-SAMPLE split
    # and named as if they were the leg's accuracy full stop, and the held-out
    # row reported 10 fixtures when only the legs with rubric guidance are held
    # out from anything. A number is allowed on the panel with its caveat, or
    # not at all.
    from eval_runner.judge_measure import held_out_effective_n_note

    main(
        [
            "--out",
            str(tmp_path / "report.md"),
            "--env-file",
            str(tmp_path / "absent.env"),
        ],
        client=_AlwaysYesJudge(),
    )

    reports = list(Path(os.environ["GATE_REPORTS_DIR"]).glob("judge-*.json"))
    rows = json.loads(reports[-1].read_text(encoding="utf-8"))["rows"]

    leg_rows = [r for r in rows if r["name"].startswith("Judge leg:")]
    assert leg_rows
    for row in leg_rows:
        assert "in-sample" in row["name"], row["name"]
        assert "undetermined" in row["result"]

    held_out_row = next(r for r in rows if "held-out" in r["name"])
    assert held_out_effective_n_note() in held_out_row["note"]


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


def _case_turn(**_kwargs):
    """A scripted turn that opens a governed case (S31's escalation EFFECT)."""
    args = {"contact_reason": "unknown", "urgency": "normal", "summary": "s"}
    return {
        "final_response": "Thanks — noted.",
        "messages": [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "toee_case__create_case",
                            "arguments": json.dumps(args),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "c1",
                "name": "toee_case__create_case",
                "content": json.dumps({"case_id": "case_1", **args}),
            },
        ],
    }


def _no_case_turn(**_kwargs):
    return {
        "final_response": "I've asked the team to reach out to you directly.",
        "messages": [],
    }


def test_the_escalation_section_is_honestly_absent_without_a_live_seam(
    tmp_path: Path,
) -> None:
    # An injected judge client with no injected turn seam must NOT quietly bill a
    # live agent loop, and must not omit the section either -- it says "not measured".
    out = tmp_path / "report.md"
    exit_code = main(
        ["--out", str(out), "--env-file", str(tmp_path / "absent.env")],
        client=_AlwaysYesJudge(),
    )

    assert exit_code == 0
    body = out.read_text(encoding="utf-8")
    assert "Live-model escalation check" in body
    assert "Not run this time" in body
    rows = json.loads(
        sorted(Path(os.environ["GATE_REPORTS_DIR"]).glob("judge-*.json"))[-1].read_text(
            encoding="utf-8"
        )
    )["rows"]
    assert not [r for r in rows if r["name"].startswith("Escalation")]


def test_every_escalation_miss_stays_advisory_and_exits_zero(tmp_path: Path) -> None:
    # The whole probe set fails (nothing escalates) -> the job STILL exits 0 and every
    # emitted row is advisory. This is the proof the leg cannot gate (NFR-4).
    from hermes_runtime.escalation_check import ESCALATION_PROBES

    out = tmp_path / "report.md"
    exit_code = main(
        ["--out", str(out), "--env-file", str(tmp_path / "absent.env")],
        client=_AlwaysYesJudge(),
        run_turn=_no_case_turn,
    )

    assert exit_code == 0
    body = out.read_text(encoding="utf-8")
    assert "Live-model escalation check" in body
    for probe in ESCALATION_PROBES:
        assert probe.name in body

    art = json.loads(
        sorted(Path(os.environ["GATE_REPORTS_DIR"]).glob("judge-*.json"))[-1].read_text(
            encoding="utf-8"
        )
    )
    # The `judge` kind is what the panel reader force-nulls `passed` on -- riding it
    # is belt and braces on top of the rows already being advisory.
    assert art["kind"] == "judge"
    escalation_rows = [r for r in art["rows"] if r["name"].startswith("Escalation")]
    assert len(escalation_rows) == 1 + len(ESCALATION_PROBES)
    assert all(r["passed"] is None for r in escalation_rows)


def test_a_probe_fault_never_fails_the_advisory_job(tmp_path: Path) -> None:
    def boom(**_kwargs):
        raise RuntimeError("provider on fire")

    out = tmp_path / "report.md"
    exit_code = main(
        ["--out", str(out), "--env-file", str(tmp_path / "absent.env")],
        client=_AlwaysYesJudge(),
        run_turn=boom,
    )

    assert exit_code == 0
    assert "provider on fire" in out.read_text(encoding="utf-8")


def test_a_clean_escalation_sheet_renders_the_rate(tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    main(
        ["--out", str(out), "--env-file", str(tmp_path / "absent.env")],
        client=_AlwaysYesJudge(),
        run_turn=_case_turn,
    )

    art = json.loads(
        sorted(Path(os.environ["GATE_REPORTS_DIR"]).glob("judge-*.json"))[-1].read_text(
            encoding="utf-8"
        )
    )
    rate_row = next(r for r in art["rows"] if "should-escalate rate" in r["name"])
    # Every probe opened a case: the should-escalate rate is perfect AND the
    # over-escalation guard fires on the same run.
    assert "2/2 = 1.000" in rate_row["result"]
    assert "unwanted cases 1 of 1" in rate_row["result"]


def test_unwritable_report_dir_never_fails_the_advisory_judge(tmp_path: Path, monkeypatch) -> None:
    # The side-report write must never affect the advisory judge's exit code (NFR-7):
    # point GATE_REPORTS_DIR under an existing FILE so the artifact mkdir raises OSError.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    monkeypatch.setenv("GATE_REPORTS_DIR", str(blocker / "sub"))

    out = tmp_path / "report.md"
    exit_code = main(
        ["--out", str(out), "--env-file", str(tmp_path / "absent.env")],
        client=_AlwaysYesJudge(),
    )

    assert exit_code == 0  # advisory judge still passes despite the failed side-write
    assert "precision `" in out.read_text(encoding="utf-8")
