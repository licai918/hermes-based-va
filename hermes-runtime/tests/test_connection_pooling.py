"""Tests for pooled Postgres connections at the 4 FR-31 sites (S29).

Two axes:

- **Lazy init / wiring** (no live Postgres needed): a mock/unset deployment
  never constructs a pool; each of the 4 sites (``PostgresDriver._acquire``,
  ``PostgresGatewayStore._connect``, ``retriever.retrieve``,
  ``datastore.handlers.knowledge._get_corpus_status``) routes its DSN-mode
  connection through the pool, not a fresh ``psycopg.connect``; the business
  and knowledge pools are always separate objects (S-ISO).
- **Bounded under concurrency** (RK-8, live Postgres, skips if unreachable):
  N concurrent operations through a pooled site never push the actual
  Postgres connection count (``pg_stat_activity``) past the pool's
  ``max_size``, proving the pool caps concurrency rather than growing
  linearly with it.
"""

from __future__ import annotations

import threading
import time

import psycopg
import pytest

from hermes_runtime.datastore.config import database_url
from hermes_runtime.knowledge.config import knowledge_database_url


# --- shared fixtures -------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_pool_singletons():
    """Every test starts with NO pool constructed, and any pool a test builds
    is closed on teardown -- process-level singletons would otherwise leak a
    pool (and its background threads) sized by one test's env override into
    the next test."""
    import hermes_runtime.datastore.pool as db_pool_mod
    import hermes_runtime.knowledge.pool as kn_pool_mod

    db_pool_mod._pools.clear()
    kn_pool_mod._pool_singleton = None
    yield
    for pool in db_pool_mod._pools.values():
        pool.close()
    db_pool_mod._pools.clear()
    if kn_pool_mod._pool_singleton is not None:
        kn_pool_mod._pool_singleton.close()
    kn_pool_mod._pool_singleton = None


class _FakePool:
    """Records ``.connection()`` checkouts; yields a trivial fake connection
    that satisfies the ``cursor()`` protocol the 4 sites use, so wiring can be
    proven without a live Postgres."""

    def __init__(self) -> None:
        self.connection_calls = 0

    def connection(self):
        self.connection_calls += 1
        return _FakeConnCtx()

    def close(self) -> None:
        pass


class _FakeConnCtx:
    def __enter__(self):
        return _FakeConn()

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeCursorCtx:
    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, *a: object, **k: object) -> None:
        pass

    def fetchone(self):
        return (0, 0, None)

    def fetchall(self):
        return []


class _FakeConn:
    def cursor(self, **kwargs: object) -> _FakeCursorCtx:
        return _FakeCursorCtx()

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


# --- lazy init: mock/unset deployments never touch Postgres ----------------


def test_constructing_a_driver_or_store_never_builds_a_pool() -> None:
    """Merely constructing the DSN-mode objects (no ``execute``/query) must
    not construct a pool -- mirrors ``select_tool_driver``'s existing
    "constructing a PostgresDriver never requires a reachable database"
    guarantee, extended to the new pool seam."""
    import hermes_runtime.datastore.pool as db_pool_mod
    import hermes_runtime.knowledge.pool as kn_pool_mod
    from hermes_runtime.datastore.driver import PostgresDriver
    from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

    PostgresDriver()
    PostgresGatewayStore()

    assert db_pool_mod._pools == {}
    assert kn_pool_mod._pool_singleton is None


def test_a_mock_backend_turn_never_builds_a_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """The mock/unset-deployment path (``TOOL_BACKEND``/``KNOWLEDGE_BACKEND``
    unset) never reaches a pooled site at all -- confirms the gating
    (``memory_enabled``/``knowledge_enabled``) upstream of pooling still
    holds, so a mock deployment stays pool-free end to end."""
    import hermes_runtime.datastore.pool as db_pool_mod
    import hermes_runtime.knowledge.pool as kn_pool_mod

    monkeypatch.delenv("TOOL_BACKEND", raising=False)
    monkeypatch.delenv("KNOWLEDGE_BACKEND", raising=False)

    from hermes_runtime.tool_backend import (
        _customer_memory_extra_drivers,
        _knowledge_extra_drivers,
        select_tool_driver,
    )

    select_tool_driver()  # -> MockDriver, no Postgres involved
    assert _customer_memory_extra_drivers() is None  # memory_enabled() is False
    assert _knowledge_extra_drivers() is None  # knowledge_enabled() is False

    assert db_pool_mod._pools == {}
    assert kn_pool_mod._pool_singleton is None


def test_get_database_pool_is_a_singleton_per_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    import hermes_runtime.datastore.pool as db_pool_mod

    monkeypatch.setattr(db_pool_mod, "ConnectionPool", lambda *a, **k: _FakePool())

    pool_a1 = db_pool_mod.get_database_pool("dsn-a")
    pool_a2 = db_pool_mod.get_database_pool("dsn-a")
    pool_b = db_pool_mod.get_database_pool("dsn-b")

    assert pool_a1 is pool_a2
    assert pool_a1 is not pool_b


def test_business_and_knowledge_pools_are_never_the_same_object(monkeypatch: pytest.MonkeyPatch) -> None:
    import hermes_runtime.datastore.pool as db_pool_mod
    import hermes_runtime.knowledge.pool as kn_pool_mod

    monkeypatch.setattr(db_pool_mod, "ConnectionPool", lambda *a, **k: _FakePool())
    monkeypatch.setattr(kn_pool_mod, "ConnectionPool", lambda *a, **k: _FakePool())

    assert db_pool_mod.get_database_pool() is not kn_pool_mod.get_knowledge_pool()


# --- the 4 sites route through the pool, not a fresh psycopg.connect -------


def test_postgres_driver_acquire_checks_out_from_the_business_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    import hermes_runtime.datastore.pool as db_pool_mod
    from hermes_runtime.datastore.driver import PostgresDriver

    fake_pool = _FakePool()
    monkeypatch.setattr(db_pool_mod, "ConnectionPool", lambda *a, **k: fake_pool)

    driver = PostgresDriver()
    with driver._acquire() as conn:
        assert isinstance(conn, _FakeConn)
    assert fake_pool.connection_calls == 1


def test_gateway_store_connect_checks_out_from_the_business_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    import hermes_runtime.datastore.pool as db_pool_mod
    from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

    fake_pool = _FakePool()
    monkeypatch.setattr(db_pool_mod, "ConnectionPool", lambda *a, **k: fake_pool)

    store = PostgresGatewayStore()
    with store._connect() as conn:
        assert isinstance(conn, _FakeConn)
    assert fake_pool.connection_calls == 1

    # The two business-DB sites (driver + gateway store) share ONE pool per DSN.
    from hermes_runtime.datastore.driver import PostgresDriver

    driver = PostgresDriver()
    with driver._acquire():
        pass
    assert fake_pool.connection_calls == 2


def test_retrieve_checks_out_from_the_knowledge_pool_when_no_conn_is_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hermes_runtime.knowledge.pool as kn_pool_mod
    from hermes_runtime.knowledge.retriever import retrieve

    fake_pool = _FakePool()
    monkeypatch.setattr(kn_pool_mod, "ConnectionPool", lambda *a, **k: fake_pool)

    # The fake connection's cursor returns no rows -> retrieve() short-circuits
    # to [] before ever needing a real embedder, exercising just the pool seam.
    assert retrieve("anything") == []
    assert fake_pool.connection_calls == 1


def test_retrieve_with_an_injected_conn_never_touches_the_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    import hermes_runtime.knowledge.pool as kn_pool_mod
    from hermes_runtime.knowledge.retriever import retrieve

    fake_pool = _FakePool()
    monkeypatch.setattr(kn_pool_mod, "ConnectionPool", lambda *a, **k: fake_pool)

    assert retrieve("anything", conn=_FakeConn()) == []
    assert fake_pool.connection_calls == 0
    assert kn_pool_mod._pool_singleton is None


def test_get_corpus_status_checks_out_from_the_knowledge_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    import hermes_runtime.knowledge.pool as kn_pool_mod
    from hermes_runtime.datastore.handlers.knowledge import _get_corpus_status

    fake_pool = _FakePool()
    monkeypatch.setattr(kn_pool_mod, "ConnectionPool", lambda *a, **k: fake_pool)

    result = _get_corpus_status(None, {}, None)

    assert fake_pool.connection_calls == 1
    assert result == {"doc_count": 0, "chunk_count": 0, "last_ingest_at": None, "by_type": []}


# --- bounded under concurrency (RK-8, live Postgres) ------------------------


def _connection_count(dsn: str, application_name: str) -> int:
    """Server-side count of backends tagged with ``application_name``, via an
    independent (non-pooled) monitoring connection so it never counts itself.

    Scoped to ``application_name`` rather than the whole database: a raw
    ``datname = current_database()`` count also picks up any other process's
    pool on the same database (e.g. a developer's own dispatch server), which
    has nothing to do with whether THIS pool caps at its max_size."""
    with psycopg.connect(dsn) as monitor_conn:
        with monitor_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE datname = current_database() AND pid <> pg_backend_pid()"
                " AND application_name = %s",
                (application_name,),
            )
            (count,) = cur.fetchone()
    return count


def _poll_max_connections_while_alive(
    dsn: str, application_name: str, threads: list[threading.Thread], *, deadline_s: float
) -> int:
    max_seen = 0
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline and any(t.is_alive() for t in threads):
        max_seen = max(max_seen, _connection_count(dsn, application_name))
        time.sleep(0.02)
    for t in threads:
        t.join(timeout=deadline_s)
    return max_seen


def test_business_pool_connection_count_stays_bounded_under_parallel_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drives 20 concurrent callers through ``PostgresGatewayStore._connect``
    (site 2's real pool seam -- ``is_duplicate`` et al. all route through this
    same method) each holding their connection for ``pg_sleep(0.15)`` -- long
    enough to force real overlap -- through a pool capped at 4, and proves the
    live Postgres connection count for the business DB never exceeds 4 -- not
    linear in the 20 concurrent callers."""
    dsn = database_url()
    try:
        psycopg.connect(dsn, connect_timeout=2).close()
    except Exception as exc:
        pytest.skip(f"Postgres unavailable at DATABASE_URL: {type(exc).__name__}: {exc}")

    monkeypatch.setenv("DATABASE_POOL_MIN_SIZE", "1")
    monkeypatch.setenv("DATABASE_POOL_MAX_SIZE", "4")

    from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

    # Tag this pool's own DSN so `_connection_count` can scope pg_stat_activity
    # to backends THIS pool opened -- other processes on the same database
    # (e.g. a developer's own dispatch server, holding its own pool) must not
    # be counted against this pool's max_size.
    application_name = "s29_business_pool_test"
    tagged_dsn = f"{dsn}?application_name={application_name}"
    store = PostgresGatewayStore(dsn=tagged_dsn)
    n_concurrent = 20

    def worker() -> None:
        with store._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_sleep(0.15)")

    threads = [threading.Thread(target=worker) for _ in range(n_concurrent)]
    for t in threads:
        t.start()

    max_seen = _poll_max_connections_while_alive(dsn, application_name, threads, deadline_s=10)

    assert max_seen <= 4, f"observed {max_seen} concurrent business-DB connections, pool max is 4"
    assert max_seen >= 2, "expected real overlap across the 20 concurrent callers, saw none"


def test_knowledge_pool_connection_count_stays_bounded_under_parallel_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same proof as the business pool, but against the SEPARATE knowledge
    pool (site 4) -- 20 concurrent checkouts through a pool capped at 3."""
    dsn = knowledge_database_url()
    try:
        psycopg.connect(dsn, connect_timeout=2).close()
    except Exception as exc:
        pytest.skip(f"Postgres unavailable at KNOWLEDGE_DATABASE_URL: {type(exc).__name__}: {exc}")

    monkeypatch.setenv("KNOWLEDGE_DATABASE_POOL_MIN_SIZE", "1")
    monkeypatch.setenv("KNOWLEDGE_DATABASE_POOL_MAX_SIZE", "3")

    # get_knowledge_pool() takes no dsn override -- tag via KNOWLEDGE_DATABASE_URL
    # itself so `_connection_count` can scope pg_stat_activity to backends THIS
    # pool opened, not any other process sharing the same database.
    application_name = "s29_knowledge_pool_test"
    tagged_dsn = f"{dsn}?application_name={application_name}"
    monkeypatch.setenv("KNOWLEDGE_DATABASE_URL", tagged_dsn)

    from hermes_runtime.knowledge.pool import get_knowledge_pool

    pool = get_knowledge_pool()
    n_concurrent = 20

    def worker() -> None:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_sleep(0.15)")

    threads = [threading.Thread(target=worker) for _ in range(n_concurrent)]
    for t in threads:
        t.start()

    max_seen = _poll_max_connections_while_alive(dsn, application_name, threads, deadline_s=10)

    assert max_seen <= 3, f"observed {max_seen} concurrent knowledge-DB connections, pool max is 3"
    assert max_seen >= 2, "expected real overlap across the 20 concurrent callers, saw none"
