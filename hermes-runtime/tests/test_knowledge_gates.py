"""Tests for the knowledge quality/latency gates harness (FR-7, FR-7b, S12).

Pure-logic tests only: recall computation and the latency/deadline harness
structure run against fake/injected retrievers, never a live DB or the real
embedder (mirrors test_knowledge_driver.py's ``retrieve_fn`` seam). Real-corpus
runs (live Postgres + real embedder) are integration-level, exercised manually
-- see the S12 report, not this suite.
"""

from __future__ import annotations

import json
import time

import pytest

from hermes_runtime.knowledge import gates
from hermes_runtime.knowledge.retriever import RetrievedChunk


def _chunk(page_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        page_id=page_id,
        page_type="page",
        title=page_id,
        url=None,
        chunk_text="text",
        score=1.0,
        fts_rank=1,
        embed_rank=1,
    )


# --- recall@3 -------------------------------------------------------------


def test_load_questions_reads_the_q_gold_json_shape(tmp_path) -> None:
    path = tmp_path / "q.json"
    path.write_text(json.dumps([{"q": "what are your hours", "gold": ["CONTACT_INFORMATION"]}]), encoding="utf-8")

    questions = gates.load_questions(path)

    assert questions == [gates.RecallCase(q="what are your hours", gold=("CONTACT_INFORMATION",))]


def test_run_recall_gate_hit_when_any_gold_page_id_is_in_top_k() -> None:
    questions = [gates.RecallCase(q="hours", gold=("CONTACT_INFORMATION", "OTHER"))]

    def _fake_retrieve(query, *, k=3, **kwargs):
        return [_chunk("nope"), _chunk("CONTACT_INFORMATION"), _chunk("also-nope")]

    report = gates.run_recall_gate(questions, retrieve_fn=_fake_retrieve)

    assert report.results[0].hit is True
    assert report.recall_at_3 == 1.0
    assert report.passed is True


def test_run_recall_gate_miss_when_no_gold_page_id_in_top_k() -> None:
    questions = [gates.RecallCase(q="hours", gold=("CONTACT_INFORMATION",))]

    def _fake_retrieve(query, *, k=3, **kwargs):
        return [_chunk("wrong-a"), _chunk("wrong-b")]

    report = gates.run_recall_gate(questions, retrieve_fn=_fake_retrieve)

    assert report.results[0].hit is False
    assert report.recall_at_3 == 0.0
    assert report.passed is False


def test_run_recall_gate_below_bar_fails_at_bar_above_recall() -> None:
    # 1/2 = 50%, below the 80% bar -> overall gate fails even though one hit.
    questions = [
        gates.RecallCase(q="a", gold=("GOOD",)),
        gates.RecallCase(q="b", gold=("GOOD2",)),
    ]

    def _fake_retrieve(query, *, k=3, **kwargs):
        return [_chunk("GOOD")] if query == "a" else [_chunk("wrong")]

    report = gates.run_recall_gate(questions, retrieve_fn=_fake_retrieve)

    assert report.recall_at_3 == pytest.approx(0.5)
    assert report.passed is False


def test_run_recall_gate_empty_question_set_is_vacuously_zero_not_a_crash() -> None:
    report = gates.run_recall_gate([], retrieve_fn=lambda query, **kw: [])
    assert report.recall_at_3 == 0.0
    assert report.results == ()


# --- latency ----------------------------------------------------------------


def test_run_latency_gate_samples_warmup_plus_rounds_times_queries() -> None:
    calls = []

    def _fast(query, **kwargs):
        calls.append(query)
        return []

    report = gates.run_latency_gate(retrieve_fn=_fast, queries=["a", "b"], warmup=1, rounds=3)

    # warmup uses queries[:warmup] = ["a"]; measured phase = rounds * len(queries) = 6
    assert len(calls) == 1 + 6
    assert len(report.samples_ms) == 6
    assert list(report.samples_ms) == sorted(report.samples_ms)  # stored sorted


def test_latency_report_percentiles_and_pass_fail_against_the_800ms_bar() -> None:
    under = gates.LatencyReport(samples_ms=tuple(float(i) for i in range(1, 101)))  # 1..100ms
    assert under.p50 == pytest.approx(51.0)
    assert under.p95 == pytest.approx(96.0)
    assert under.passed is True

    over = gates.LatencyReport(samples_ms=(900.0,) * 20)
    assert over.p95 == pytest.approx(900.0)
    assert over.passed is False


def test_run_latency_gate_actually_times_a_sleeping_fake_retriever() -> None:
    def _slow(query, **kwargs):
        time.sleep(0.005)
        return []

    report = gates.run_latency_gate(retrieve_fn=_slow, queries=["a"], warmup=0, rounds=2)

    assert report.samples_ms[0] >= 4.0  # ~5ms sleep, generous floor for CI jitter


# --- deadline degrade (KnowledgeDriver, forced-slow path) -------------------


def test_deadline_degrade_check_returns_governed_miss_bounded_by_the_deadline() -> None:
    result = gates.run_deadline_degrade_check(deadline_ms=50, sleep_s=1.0)

    assert result.governed_miss is True
    assert result.passed is True
    assert result.elapsed_ms < 900  # bounded by the 50ms deadline, not the 1s sleep


def test_deadline_degrade_check_fails_if_somehow_not_governed_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    # Sanity on the .passed property itself, independent of the real driver.
    result = gates.DeadlineCheckResult(governed_miss=False, elapsed_ms=10.0, deadline_ms=50)
    assert result.passed is False


# --- CLI shape ----------------------------------------------------------------


def test_cmd_recall_prints_per_question_and_overall_and_exits_by_pass_fail(tmp_path, monkeypatch, capsys) -> None:
    path = tmp_path / "q.json"
    path.write_text(
        json.dumps([{"q": "hours", "gold": ["CONTACT_INFORMATION"]}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(gates, "retrieve", lambda query, **kw: [_chunk("CONTACT_INFORMATION")])

    code = gates.main(["recall", str(path)])
    out = capsys.readouterr().out

    assert code == 0
    assert "HIT" in out
    assert "recall@3" in out
    assert "PASS" in out


def test_cmd_recall_defaults_to_the_checked_in_fixture_when_no_path_given(monkeypatch, capsys) -> None:
    monkeypatch.setattr(gates, "retrieve", lambda query, **kw: [])

    code = gates.main(["recall"])
    out = capsys.readouterr().out

    assert code == 1  # every question misses against the always-empty fake
    assert "recall@3" in out


def test_main_with_no_subcommand_prints_usage_and_returns_2(capsys) -> None:
    code = gates.main([])
    err = capsys.readouterr().err
    assert code == 2
    assert "usage" in err.lower()
