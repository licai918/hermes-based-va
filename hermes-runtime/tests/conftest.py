"""Shared fixtures for hermes-runtime datastore integration tests.

These talk to the docker-compose Postgres at ``DATABASE_URL`` and isolate each
test in a throwaway schema, so they never touch dev data and **skip** (not fail)
when no Postgres is reachable (ADR-0142 local-first).
"""

from __future__ import annotations

import uuid

import pytest

from hermes_runtime.datastore.config import database_url
from hermes_runtime.datastore.migrate import run_migrations

try:  # psycopg lives in the hermes-runtime venv (ADR-0142); guard for safety.
    import psycopg
except ImportError:  # pragma: no cover - exercised only without the driver
    psycopg = None  # type: ignore[assignment]


@pytest.fixture
def temp_schema_conn():
    """An open connection whose search_path points at a fresh throwaway schema."""
    if psycopg is None:
        pytest.skip("psycopg not installed")
    from psycopg import sql

    try:
        # connect_timeout so an unreachable/black-holed host (Docker down, IPv6
        # localhost SYN drop) skips fast instead of hanging forever in select().
        conn = psycopg.connect(database_url(), connect_timeout=2)
    except Exception as exc:  # OperationalError and friends -> no DB available.
        pytest.skip(f"no Postgres at DATABASE_URL: {exc}")

    schema = f"test_{uuid.uuid4().hex[:12]}"
    schema_id = sql.Identifier(schema)
    with conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA {}").format(schema_id))
        cur.execute(sql.SQL("SET search_path TO {}").format(schema_id))
    conn.commit()
    try:
        yield conn, schema
    finally:
        # A failed unit of work leaves the transaction aborted; clear it so the
        # DROP can run instead of raising a confusing secondary error.
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(schema_id))
        conn.commit()
        conn.close()


@pytest.fixture
def datastore(temp_schema_conn):
    """A migrated throwaway schema + a PostgresDriver bound to its connection.

    Yields ``(driver, conn, schema)``. The driver shares the fixture connection
    so its writes land in the same isolated schema the test can read back.
    """
    conn, schema = temp_schema_conn
    run_migrations(conn)
    from hermes_runtime.datastore.driver import PostgresDriver

    return PostgresDriver(connection=conn), conn, schema
