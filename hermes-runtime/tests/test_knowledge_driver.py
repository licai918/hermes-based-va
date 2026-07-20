"""Tests for the ``toee_knowledge_search`` governed driver (FR-4, NFR-5, S09).

``retrieve`` is injected via ``retrieve_fn`` so these tests never import
fastembed/psycopg (mirrors ``test_knowledge_retriever.py``'s fake-embedder
seam). A live smoke test against the real corpus + embedder is run manually,
not part of this suite (see the S09 report).
"""

from __future__ import annotations

import logging
import threading
import time

import pytest

from toee_hermes.execute import ToolRequest
from toee_hermes.tool_gate import ToolExecutionContext

from hermes_runtime.knowledge.driver import (
    KNOWLEDGE_BACKEND_ENV,
    KnowledgeDriver,
    knowledge_enabled,
    warm_knowledge_embedder,
)
from hermes_runtime.knowledge.retriever import RetrievedChunk

_CTX = ToolExecutionContext(profile="external")


def _chunk(title: str = "Contact & Store Hours", url: str = "https://x.test/contact") -> RetrievedChunk:
    return RetrievedChunk(
        page_id="p1",
        page_type="page",
        title=title,
        url=url,
        chunk_text="How to reach Toee Tire support and current service hours.",
        score=1.0,
        fts_rank=1,
        embed_rank=1,
    )


# --- knowledge_enabled() gate --------------------------------------------


def test_knowledge_enabled_false_when_unset_or_empty() -> None:
    assert knowledge_enabled(None) is False
    assert knowledge_enabled("") is False


def test_knowledge_enabled_false_for_unrelated_value() -> None:
    assert knowledge_enabled("datastore") is False


def test_knowledge_enabled_true_for_retriever() -> None:
    assert knowledge_enabled("retriever") is True


def test_knowledge_enabled_reads_its_own_env_var_independent_of_tool_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(KNOWLEDGE_BACKEND_ENV, raising=False)
    monkeypatch.setenv("TOOL_BACKEND", "datastore")  # unrelated axis
    assert knowledge_enabled() is False

    monkeypatch.setenv(KNOWLEDGE_BACKEND_ENV, "retriever")
    assert knowledge_enabled() is True


# --- search_public_site happy path ---------------------------------------


def test_search_public_site_happy_path_matches_mock_shape_plus_chunk_text() -> None:
    driver = KnowledgeDriver(retrieve_fn=lambda query, **kw: [_chunk()])
    request = ToolRequest(tool="toee_knowledge_search", action="search_public_site", params={"query": "hours"})

    result = driver.execute(request, _CTX)

    assert result == {
        "results": [
            {
                "title": "Contact & Store Hours",
                "url": "https://x.test/contact",
                "snippet": "How to reach Toee Tire support and current service hours.",
                "chunk_text": "How to reach Toee Tire support and current service hours.",
            }
        ]
    }


def test_search_public_site_no_chunks_is_the_governed_miss() -> None:
    driver = KnowledgeDriver(retrieve_fn=lambda query, **kw: [])
    request = ToolRequest(tool="toee_knowledge_search", action="search_public_site", params={"query": "nope"})

    assert driver.execute(request, _CTX) == {"results": []}


# --- deadline ---------------------------------------------------------


def _slow_retrieve(seconds: float):
    def _fn(query: str, **kwargs):
        time.sleep(seconds)
        return [_chunk()]

    return _fn


def test_deadline_overrun_returns_governed_miss_bounded_by_wall_clock() -> None:
    driver = KnowledgeDriver(retrieve_fn=_slow_retrieve(2.0), deadline_ms=50)
    request = ToolRequest(tool="toee_knowledge_search", action="search_public_site", params={"query": "slow"})

    start = time.monotonic()
    result = driver.execute(request, _CTX)
    elapsed = time.monotonic() - start

    assert result == {"results": []}
    assert elapsed < 1.0  # bounded by the 50ms deadline, not the 2s sleep


def test_retriever_exception_returns_governed_miss_never_raises() -> None:
    def _boom(query: str, **kwargs):
        raise RuntimeError("db unreachable")

    driver = KnowledgeDriver(retrieve_fn=_boom)
    request = ToolRequest(tool="toee_knowledge_search", action="search_public_site", params={"query": "boom"})

    assert driver.execute(request, _CTX) == {"results": []}


# --- search_operational_policy delegates unchanged ------------------------


class _RecordingFallback:
    kind = "mock"

    def __init__(self) -> None:
        self.calls: list[ToolRequest] = []

    def execute(self, request: ToolRequest, context: ToolExecutionContext):
        self.calls.append(request)
        return {"slot": "return_policy", "content": "policy text", "found": True}


def test_search_operational_policy_delegates_to_fallback_driver_unchanged() -> None:
    fallback = _RecordingFallback()
    driver = KnowledgeDriver(fallback_driver=fallback, retrieve_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call retrieve")))
    request = ToolRequest(
        tool="toee_knowledge_search", action="search_operational_policy", params={"slot": "return_policy"}
    )

    result = driver.execute(request, _CTX)

    assert result == {"slot": "return_policy", "content": "policy text", "found": True}
    assert fallback.calls == [request]


# --- log sanitization (FR-4) ----------------------------------------------


def test_query_text_never_appears_in_logs_on_timeout(caplog: pytest.LogCaptureFixture) -> None:
    secret_query = "super-secret-customer-question-xyz"
    driver = KnowledgeDriver(retrieve_fn=_slow_retrieve(2.0), deadline_ms=20)
    request = ToolRequest(
        tool="toee_knowledge_search", action="search_public_site", params={"query": secret_query}
    )

    with caplog.at_level(logging.WARNING):
        driver.execute(request, _CTX)

    for record in caplog.records:
        assert secret_query not in record.getMessage()


def test_query_text_never_appears_in_logs_on_exception(caplog: pytest.LogCaptureFixture) -> None:
    secret_query = "another-secret-question-abc"

    def _boom(query: str, **kwargs):
        raise RuntimeError("db unreachable")

    driver = KnowledgeDriver(retrieve_fn=_boom)
    request = ToolRequest(
        tool="toee_knowledge_search", action="search_public_site", params={"query": secret_query}
    )

    with caplog.at_level(logging.WARNING):
        driver.execute(request, _CTX)

    for record in caplog.records:
        assert secret_query not in record.getMessage()


# --- extra_drivers overlay (tool_backend.py) -------------------------------


def test_knowledge_extra_drivers_none_when_gate_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from hermes_runtime.tool_backend import _knowledge_extra_drivers

    monkeypatch.delenv(KNOWLEDGE_BACKEND_ENV, raising=False)
    assert _knowledge_extra_drivers() is None


def test_knowledge_extra_drivers_present_when_gate_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from hermes_runtime.tool_backend import _knowledge_extra_drivers

    monkeypatch.setenv(KNOWLEDGE_BACKEND_ENV, "retriever")
    overlay = _knowledge_extra_drivers()

    assert overlay is not None
    assert set(overlay.keys()) == {"toee_knowledge_search"}


# --- warm_knowledge_embedder (S10 cold-load mitigation) --------------------


def test_warm_knowledge_embedder_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(KNOWLEDGE_BACKEND_ENV, raising=False)
    import hermes_runtime.knowledge.driver as driver_mod

    def _must_not_start(*_a, **_k):
        raise AssertionError("no warmup thread should start when knowledge is disabled")

    monkeypatch.setattr(driver_mod.threading, "Thread", _must_not_start)

    warm_knowledge_embedder()  # returns immediately -- no thread constructed


def test_warm_knowledge_embedder_fires_the_embedder_in_the_background(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(KNOWLEDGE_BACKEND_ENV, "retriever")
    calls: list[str] = []
    done = threading.Event()

    def _fake_embedder():
        def _embed(query: str):
            calls.append(query)
            done.set()
            return [0.0]

        return _embed

    import hermes_runtime.knowledge.retriever as retriever_mod

    monkeypatch.setattr(retriever_mod, "fastembed_query_embedder", _fake_embedder)

    warm_knowledge_embedder()

    assert done.wait(timeout=2.0), "warmup did not call the embedder in time"
    assert calls == ["warmup"]


def test_warm_knowledge_embedder_swallows_and_logs_a_failing_embedder(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(KNOWLEDGE_BACKEND_ENV, "retriever")

    def _boom():
        def _embed(query: str):
            raise RuntimeError("model load failed")

        return _embed

    import hermes_runtime.knowledge.retriever as retriever_mod

    monkeypatch.setattr(retriever_mod, "fastembed_query_embedder", _boom)

    with caplog.at_level(logging.WARNING):
        warm_knowledge_embedder()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not caplog.records:
            time.sleep(0.01)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "warmup" in warnings[0].getMessage().lower()
    assert "RuntimeError" in warnings[0].getMessage()
