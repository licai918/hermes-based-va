"""Knowledge quality + latency gates harness (FR-7, FR-7b, S12).

Productionizes the throwaway spike probes
(``workspace/0.0.3/knowledge-spike/probe/squal_embed.py`` and ``slat.py``) as
checked-in, repeatable commands over the REAL :func:`~hermes_runtime.knowledge.
retriever.retrieve` -- S27's review flagged that the spike's numbers weren't
reproducible from committed code; this closes that class of gap for knowledge.

Two gates:

- **recall@3** (FR-7): a labelled ``[{q, gold:[page_id...]}]`` question set
  run through the real hybrid retriever; a question is a HIT if any gold
  ``page_id`` appears among the top-``k`` chunks' page ids. Bar: 80%. Seeded
  with the spike's 30 synthetic questions, copied verbatim into
  ``fixtures/synthetic_gate_questions.json`` -- this is the INTERIM dev-time
  set; the real ~30-owner-question final gate is S32.
- **hybrid in-turn latency** (FR-7b, audit finding 1): p95 wall-clock for one
  ``retrieve()`` call -- SQL + query-embedding inference included -- gated at
  under 800ms, plus a check that the driver-side deadline (``KnowledgeDriver``,
  S09) still degrades a forced-slow path to the governed miss instead of
  hanging the turn.

CLI::

    python -m hermes_runtime.knowledge.gates recall [questions.json]
    python -m hermes_runtime.knowledge.gates latency

Both commands exit 0 on PASS, 1 on FAIL (these are gates, not advisory
measurements like ``eval_runner.judge_measure``) -- CI-safe by not being wired
into CI: they require a live Postgres + the real embedder, so they are run
manually / from an ops runbook, same posture as ``judge_measure --live``.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from .driver import DEFAULT_DEADLINE_MS
from .retriever import RetrievedChunk, get_query_embedder, retrieve

RECALL_BAR = 0.80
LATENCY_P95_BUDGET_MS = 800.0

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DEFAULT_QUESTIONS_PATH = FIXTURES_DIR / "synthetic_gate_questions.json"

RetrieveFn = Callable[..., list[RetrievedChunk]]

# Same 20 queries the S-LAT spike used (workspace/0.0.3/knowledge-spike/probe/slat.py)
# -- a mix of real corpus topics, representative of in-turn query shape.
LATENCY_QUERIES = [
    "return policy", "winter tires", "how to read sidewall numbers", "shipping options",
    "warranty", "dealer program", "vip points", "payment methods", "brand story",
    "grenlander", "windforce", "tire pressure", "business hours", "bulk order discount",
    "set up account", "all season tires", "refund", "who are you", "delivery time", "snow tires",
]


# --- recall@3 (FR-7) ---------------------------------------------------------


@dataclass(frozen=True)
class RecallCase:
    q: str
    gold: tuple[str, ...]


@dataclass(frozen=True)
class RecallResult:
    case: RecallCase
    got_page_ids: tuple[str, ...]
    hit: bool


@dataclass(frozen=True)
class RecallReport:
    results: tuple[RecallResult, ...]

    @property
    def recall_at_3(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.hit) / len(self.results)

    @property
    def passed(self) -> bool:
        return self.recall_at_3 >= RECALL_BAR


def load_questions(path: str | Path) -> list[RecallCase]:
    """Load a ``[{"q": ..., "gold": [page_id, ...]}, ...]`` labelled set."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [RecallCase(q=item["q"], gold=tuple(item["gold"])) for item in data]


def run_recall_gate(
    questions: Sequence[RecallCase],
    *,
    retrieve_fn: RetrieveFn = retrieve,
    k: int = 3,
    **retrieve_kwargs: Any,
) -> RecallReport:
    """Run every question through ``retrieve_fn`` (default: the real hybrid
    retriever) and score recall@``k``. Never raises on a miss -- a miss is a
    normal, reportable result, not an error."""
    results = []
    for case in questions:
        chunks = retrieve_fn(case.q, k=k, **retrieve_kwargs)
        got = tuple(c.page_id for c in chunks)
        hit = any(g in got for g in case.gold)
        results.append(RecallResult(case=case, got_page_ids=got, hit=hit))
    return RecallReport(tuple(results))


# --- hybrid in-turn latency (FR-7b) ------------------------------------------


def _pct(sorted_ms: Sequence[float], fraction: float) -> float:
    return sorted_ms[min(len(sorted_ms) - 1, int(fraction * len(sorted_ms)))]


@dataclass(frozen=True)
class LatencyReport:
    samples_ms: tuple[float, ...]  # sorted ascending

    @property
    def p50(self) -> float:
        return _pct(self.samples_ms, 0.5)

    @property
    def p95(self) -> float:
        return _pct(self.samples_ms, 0.95)

    @property
    def p99(self) -> float:
        return _pct(self.samples_ms, 0.99)

    @property
    def passed(self) -> bool:
        return self.p95 < LATENCY_P95_BUDGET_MS


def run_latency_gate(
    *,
    retrieve_fn: RetrieveFn = retrieve,
    queries: Sequence[str] = LATENCY_QUERIES,
    warmup: int = 5,
    rounds: int = 10,
    **retrieve_kwargs: Any,
) -> LatencyReport:
    """Time ``rounds * len(queries)`` calls to ``retrieve_fn`` after a short
    warmup phase (``queries[:warmup]``, uncounted). Caller is responsible for
    warming the query-embedder singleton first (:func:`get_query_embedder`)
    so this measures steady state, not the ~800ms onnx cold-load -- the CLI
    does this before calling in.
    """
    for q in queries[:warmup]:
        retrieve_fn(q, **retrieve_kwargs)

    samples: list[float] = []
    for _ in range(rounds):
        for q in queries:
            t0 = time.perf_counter()
            retrieve_fn(q, **retrieve_kwargs)
            samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    return LatencyReport(tuple(samples))


@dataclass(frozen=True)
class DeadlineCheckResult:
    governed_miss: bool
    elapsed_ms: float
    deadline_ms: float

    @property
    def passed(self) -> bool:
        # Governed miss AND bounded well under the forced sleep -- proves the
        # deadline (not the sleep finishing) ended the call, i.e. no turn hang.
        return self.governed_miss and self.elapsed_ms < self.deadline_ms + 500


def run_deadline_degrade_check(
    *, deadline_ms: float = DEFAULT_DEADLINE_MS, sleep_s: float = 2.0
) -> DeadlineCheckResult:
    """Force the S09 ``KnowledgeDriver``'s slow path (a retriever that never
    returns before the deadline) and confirm it degrades to the governed
    no-match shape (``{"results": []}``) instead of hanging the turn (NFR-5).
    Re-verifies the deadline mechanism specifically around the HYBRID rung's
    driver, per FR-7b ("re-verify the S09 deadline degrade around the slower
    path") -- not just the raw ``statement_timeout`` the spike's S-LAT probed.
    """
    from toee_hermes.execute import ToolRequest
    from toee_hermes.tool_gate import ToolExecutionContext

    from .driver import KnowledgeDriver

    def _forced_slow(query: str, **kwargs: Any) -> list[RetrievedChunk]:
        time.sleep(sleep_s)
        return [RetrievedChunk("never-seen", "page", "t", None, "x", 1.0, 1, 1)]

    driver = KnowledgeDriver(retrieve_fn=_forced_slow, deadline_ms=deadline_ms)
    request = ToolRequest(tool="toee_knowledge_search", action="search_public_site", params={"query": "gate-probe"})
    context = ToolExecutionContext(profile="external")

    t0 = time.perf_counter()
    result = driver.execute(request, context)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    return DeadlineCheckResult(governed_miss=result == {"results": []}, elapsed_ms=elapsed_ms, deadline_ms=deadline_ms)


# --- CLI ----------------------------------------------------------------------


def _cmd_recall(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else DEFAULT_QUESTIONS_PATH
    questions = load_questions(path)
    # Pass the module global explicitly (a call-time lookup) rather than
    # relying on run_recall_gate's default parameter, which binds `retrieve`
    # at module-import time -- tests monkeypatch gates.retrieve and need that
    # rebinding to actually take effect here.
    report = run_recall_gate(questions, retrieve_fn=retrieve)

    print(f"recall@3 gate -- {path} ({len(questions)} questions)")
    for r in report.results:
        status = "HIT " if r.hit else "MISS"
        print(f"  [{status}] {r.case.q!r} gold={list(r.case.gold)} got={list(r.got_page_ids)}")
    hits = sum(1 for r in report.results if r.hit)
    print(
        f"recall@3 = {hits}/{len(report.results)} = {report.recall_at_3:.0%}  "
        f"[bar {RECALL_BAR:.0%}: {'PASS' if report.passed else 'FAIL'}]"
    )
    return 0 if report.passed else 1


def _cmd_latency(argv: list[str]) -> int:
    print("warming the query embedder (steady-state measurement, not cold-load)...")
    get_query_embedder()("warmup")

    report = run_latency_gate()
    print(f"hybrid in-turn latency -- {len(report.samples_ms)} retrieve() calls (embedding inference included)")
    print(f"  p50={report.p50:.2f}ms  p95={report.p95:.2f}ms  p99={report.p99:.2f}ms  max={report.samples_ms[-1]:.2f}ms")
    print(f"  [FR-7b latency gate] p95 < {LATENCY_P95_BUDGET_MS:.0f}ms: {'PASS' if report.passed else 'FAIL'}")

    degrade = run_deadline_degrade_check()
    print(
        f"deadline degrade (forced-slow path, deadline_ms={degrade.deadline_ms:.0f}): "
        f"governed_miss={degrade.governed_miss} elapsed={degrade.elapsed_ms:.0f}ms"
    )
    print(f"  [FR-7b deadline degrade] slow path -> found=false, no hang: {'PASS' if degrade.passed else 'FAIL'}")

    return 0 if (report.passed and degrade.passed) else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in ("recall", "latency"):
        print("usage: python -m hermes_runtime.knowledge.gates {recall|latency} [questions.json]", file=sys.stderr)
        return 2
    cmd, rest = args[0], args[1:]
    return _cmd_recall(rest) if cmd == "recall" else _cmd_latency(rest)


if __name__ == "__main__":  # pragma: no cover - thin CLI shell
    raise SystemExit(main())
