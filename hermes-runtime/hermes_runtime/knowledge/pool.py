"""Process-level pooled Postgres connections for the knowledge DB (S29, FR-31).

FR-31 site 4: the retriever (``retriever.py``) and the datastore knowledge-ops
corpus-status handler (``datastore/handlers/knowledge.py``) both talk to the
knowledge database (``KNOWLEDGE_DATABASE_URL``) and share the pool built here.
A SEPARATE pool from the business DB's (``datastore/pool.py``) -- the S-ISO
isolation invariant: the knowledge store is a different Postgres database and
never shares a connection or a pool with the business DB.

Lazily constructed: the pool is built on first call to :func:`get_knowledge_pool`,
never at import, so a deployment with knowledge retrieval disabled
(``KNOWLEDGE_BACKEND`` unset) never constructs a pool or touches Postgres --
same discipline as ``knowledge.driver.knowledge_enabled`` gating. Process-level
singleton, lock-guarded construction (mirrors the S10 embedder singleton,
``retriever.get_query_embedder``, and ``datastore.pool.get_database_pool``).
"""

from __future__ import annotations

import os
import threading

from psycopg_pool import ConnectionPool

from .config import knowledge_database_url

POOL_MIN_SIZE_ENV = "KNOWLEDGE_DATABASE_POOL_MIN_SIZE"
POOL_MAX_SIZE_ENV = "KNOWLEDGE_DATABASE_POOL_MAX_SIZE"
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


_pool_lock = threading.Lock()
_pool_singleton: ConnectionPool | None = None


def get_knowledge_pool() -> ConnectionPool:
    """Process-level singleton connection pool for the knowledge DB.

    Built lazily on first call -- never at import. No caller ever overrides
    the knowledge DSN (unlike the business DB's ``dsn=`` constructor param),
    so this is a single global singleton rather than the per-DSN dict
    ``datastore.pool.get_database_pool`` uses.
    """
    global _pool_singleton
    with _pool_lock:
        if _pool_singleton is None:
            _pool_singleton = ConnectionPool(
                knowledge_database_url(),
                min_size=_int_env(POOL_MIN_SIZE_ENV, DEFAULT_POOL_MIN_SIZE),
                max_size=_int_env(POOL_MAX_SIZE_ENV, DEFAULT_POOL_MAX_SIZE),
                open=True,
            )
        return _pool_singleton
