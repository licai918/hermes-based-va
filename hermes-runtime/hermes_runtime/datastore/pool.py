"""Process-level pooled Postgres connections for the business DB (S29, FR-31).

FR-31 sites 1-3 (the dispatch/per-turn ``PostgresDriver`` -- ``driver.py`` --
which backs BOTH the tools:dispatch server and the per-turn ``extra_drivers``
overlays -- and the gateway store, ``postgres_gateway_store.py``) all talk to
the SAME business database (``DATABASE_URL``) and share the pool built here.
The knowledge DB is a SEPARATE Postgres database (``KNOWLEDGE_DATABASE_URL``)
and gets its OWN pool (``knowledge/pool.py``) -- the two are never crossed
(S-ISO isolation invariant).

Lazily constructed: the pool is built on first call to :func:`get_database_pool`,
never at import, so a mock/unset deployment (``TOOL_BACKEND`` unset) never
constructs a pool or touches Postgres -- same discipline as
``tool_backend.select_tool_driver``/``_gateway_store``. One pool per distinct
DSN (a real deployment only ever resolves one), process-level singleton,
lock-guarded construction (mirrors the S10 embedder singleton,
``knowledge.retriever.get_query_embedder``).
"""

from __future__ import annotations

import os
import threading

from psycopg_pool import ConnectionPool

from .config import database_url

# Sizing knobs, env-overridable with sane local-first defaults. max_size bounds
# the connection count under concurrent load (RK-8); min_size keeps pool
# startup cheap (grown lazily by the pool's own background workers up to
# max_size as demand requires).
POOL_MIN_SIZE_ENV = "DATABASE_POOL_MIN_SIZE"
POOL_MAX_SIZE_ENV = "DATABASE_POOL_MAX_SIZE"
DEFAULT_POOL_MIN_SIZE = 1
DEFAULT_POOL_MAX_SIZE = 10


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


_pools: dict[str, ConnectionPool] = {}
_pools_lock = threading.Lock()


def get_database_pool(dsn: str | None = None) -> ConnectionPool:
    """Process-level singleton pool for ``dsn`` (default: :func:`database_url`).

    Built lazily on first call -- never at import -- so constructing a
    :class:`~hermes_runtime.datastore.driver.PostgresDriver` /
    :class:`~hermes_runtime.postgres_gateway_store.PostgresGatewayStore`
    without ever executing a DSN-mode operation never touches Postgres. One
    pool per distinct DSN (keyed by the resolved string), so callers that pass
    a custom ``dsn=`` still get their OWN pool rather than silently sharing
    the default one. The lock only guards the check-and-build; the pooled
    connection itself is used outside the lock, so concurrent turns still get
    real concurrency.
    """
    resolved_dsn = dsn or database_url()
    with _pools_lock:
        pool = _pools.get(resolved_dsn)
        if pool is None:
            pool = ConnectionPool(
                resolved_dsn,
                min_size=_int_env(POOL_MIN_SIZE_ENV, DEFAULT_POOL_MIN_SIZE),
                max_size=_int_env(POOL_MAX_SIZE_ENV, DEFAULT_POOL_MAX_SIZE),
                open=True,
            )
            _pools[resolved_dsn] = pool
        return pool
