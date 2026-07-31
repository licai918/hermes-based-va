"""Tests for the fire-and-forget metric-event emit (0.0.3 S26, FR-28).

``emit_metric_event`` is the shared seam both GAP counters (memory injection,
knowledge found/miss) use. It must be turn-safe (NFR-5): ANY failure --
missing DSN, unreachable Postgres, missing table -- is caught and logged by
TYPE ONLY, never raised into the caller (a metrics emit must never fail a
turn or a knowledge search).
"""

from __future__ import annotations

import logging

import pytest

from hermes_runtime.datastore.config import CONNECT_TIMEOUT_TURN_SECONDS
from hermes_runtime.metrics import (
    KNOWLEDGE_SEARCH,
    MEMORY_INJECTION,
    emit_metric_event,
)


class _FakeCursor:
    def __init__(self, calls: list[tuple[str, tuple]]) -> None:
        self._calls = calls

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple) -> None:
        self._calls.append((sql, params))


class _FakeConn:
    def __init__(self, calls: list[tuple[str, tuple]]) -> None:
        self._calls = calls
        self.committed = False

    def __enter__(self) -> "_FakeConn":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._calls)

    def commit(self) -> None:
        self.committed = True


def test_emit_metric_event_inserts_one_row_with_metric_and_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, tuple]] = []
    conn = _FakeConn(calls)
    connect_kwargs: dict[str, object] = {}

    def _connect(dsn: str, **kwargs: object) -> _FakeConn:
        connect_kwargs.update(kwargs)
        return conn

    monkeypatch.setattr("hermes_runtime.metrics.psycopg.connect", _connect)

    emit_metric_event(MEMORY_INJECTION, True)

    # The emit is on the turn path, so the connect must be bounded. Asserted
    # here rather than only in test_connect_timeouts.py because THIS fake is
    # what would hide a regression: emit_metric_event swallows every
    # exception, so a fake whose signature no longer matches the call fails as
    # a silent zero-insert rather than as an error.
    assert connect_kwargs.get("connect_timeout") == CONNECT_TIMEOUT_TURN_SECONDS

    assert len(calls) == 1
    sql, params = calls[0]
    assert "INSERT INTO metric_event" in sql
    assert params[1] == MEMORY_INJECTION
    assert params[2] is True
    assert conn.committed is True


def test_emit_metric_event_never_raises_on_connect_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _boom(dsn: str, **kwargs: object) -> None:
        raise RuntimeError("connection refused")

    monkeypatch.setattr("hermes_runtime.metrics.psycopg.connect", _boom)

    with caplog.at_level(logging.WARNING):
        emit_metric_event(KNOWLEDGE_SEARCH, False)  # must not raise

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "RuntimeError" in warnings[0].getMessage()
    # No customer/query content ever appears -- metric name + type only.
    assert KNOWLEDGE_SEARCH in warnings[0].getMessage()


def test_emit_metric_event_never_raises_on_insert_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class _BoomCursor(_FakeCursor):
        def execute(self, sql: str, params: tuple) -> None:
            raise RuntimeError("relation \"metric_event\" does not exist")

    class _BoomConn(_FakeConn):
        def cursor(self) -> _BoomCursor:  # type: ignore[override]
            return _BoomCursor([])

    monkeypatch.setattr(
        "hermes_runtime.metrics.psycopg.connect",
        lambda dsn, **kwargs: _BoomConn([]),
    )

    with caplog.at_level(logging.WARNING):
        emit_metric_event(MEMORY_INJECTION, True)  # must not raise

    # Pin that the INSERT is what failed. Without this the test passes when the
    # connect fails first for an unrelated reason -- which is exactly what
    # happened when connect_timeout was added and this fake's signature went
    # stale: a test named "on_insert_failure" that never reached the insert.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "RuntimeError" in warnings[0].getMessage()
