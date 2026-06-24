"""Integration tests for the local Toee Business Datastore migration runner.

Slice 32 / #35 (ADR-0140 system-of-record, ADR-0142 local-first). These run
against the docker-compose Postgres at ``DATABASE_URL`` and are isolated in a
throwaway schema so they never touch dev data. They **skip** (not fail) when no
Postgres is reachable, so the suite stays green without a database; CI gets a
Postgres service container in a later slice.
"""

from __future__ import annotations

import uuid

import pytest

from hermes_runtime.datastore.config import database_url
from hermes_runtime.datastore.migrate import discover_migrations, run_migrations

try:  # psycopg lives in the hermes-runtime venv (ADR-0142); guard for safety.
    import psycopg
except ImportError:  # pragma: no cover - exercised only without the driver
    psycopg = None  # type: ignore[assignment]


# System-of-record tables the first migration must create (ADR-0140 entity list,
# ADR-0115 conversation hierarchy), plus the runner's own bookkeeping table.
EXPECTED_TABLES = {
    "schema_migrations",
    "identity_link",
    "session_identity_snapshot",
    "customer_thread",
    "sms_session",
    "message_turn",
    "agent_turn_context",
    "customer_memory_slot",
    "customer_memory_merge_audit",
    "cases",
    "workbench_audit_log",
    "workbench_account",
    "knowledge_version",
    "eval_run",
}


@pytest.fixture
def temp_schema_conn():
    """An open connection whose search_path points at a fresh throwaway schema."""
    if psycopg is None:
        pytest.skip("psycopg not installed")
    try:
        conn = psycopg.connect(database_url())
    except Exception as exc:  # OperationalError and friends -> no DB available.
        pytest.skip(f"no Postgres at DATABASE_URL: {exc}")

    schema = f"test_migrate_{uuid.uuid4().hex[:12]}"
    with conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA "{schema}"')
        cur.execute(f'SET search_path TO "{schema}"')
    conn.commit()
    try:
        yield conn, schema
    finally:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        conn.commit()
        conn.close()


def _tables_in(conn, schema: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            (schema,),
        )
        return {row[0] for row in cur.fetchall()}


def _tables_with_column(conn, schema: str, column: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name FROM information_schema.columns
            WHERE table_schema = %s AND column_name = %s
            """,
            (schema, column),
        )
        return {row[0] for row in cur.fetchall()}


def test_discover_migrations_is_ordered_and_nonempty() -> None:
    migrations = discover_migrations()
    assert migrations, "expected at least one .sql migration on disk"
    versions = [version for version, _ in migrations]
    assert versions == sorted(versions), "migrations must apply in lexical order"
    assert versions[0] == "0001_initial_schema"


def test_migrations_create_all_system_of_record_tables(temp_schema_conn) -> None:
    conn, schema = temp_schema_conn
    applied = run_migrations(conn)
    assert "0001_initial_schema" in applied
    missing = EXPECTED_TABLES - _tables_in(conn, schema)
    assert not missing, f"missing tables after migrate: {sorted(missing)}"


def test_migrations_are_idempotent(temp_schema_conn) -> None:
    conn, _ = temp_schema_conn
    first = run_migrations(conn)
    assert first, "first run should apply at least one migration"
    second = run_migrations(conn)
    assert second == [], "second run must be a no-op (nothing pending)"


def test_retention_timestamp_columns_present(temp_schema_conn) -> None:
    conn, schema = temp_schema_conn
    run_migrations(conn)
    with_created = _tables_with_column(conn, schema, "created_at")
    # Retention is enforced off created_at on these classes (ADR-0004/0116).
    for table in ("cases", "message_turn", "workbench_audit_log", "customer_memory_slot"):
        assert table in with_created, f"{table} must carry created_at for retention"
