"""Integration tests for the local Toee Business Datastore migration runner.

Slice 32 / #35 (ADR-0140 system-of-record, ADR-0142 local-first). These run
against the docker-compose Postgres at ``DATABASE_URL`` and are isolated in a
throwaway schema so they never touch dev data. They **skip** (not fail) when no
Postgres is reachable, so the suite stays green without a database; CI gets a
Postgres service container in a later slice.
"""

from __future__ import annotations

from hermes_runtime.datastore.migrate import discover_migrations, run_migrations

# The ``temp_schema_conn`` fixture (throwaway schema, skip-if-no-DB) is shared
# from tests/conftest.py.


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


def test_initial_migration_declares_every_system_of_record_table() -> None:
    """No-DB CI guard for the Slice 32 acceptance criterion: the first migration
    must declare every system-of-record table. The live-DB tests below skip when
    no Postgres is reachable, so without this a dropped/renamed table would ship
    behind green CI until a Postgres service container lands."""
    version, sql_text = discover_migrations()[0]
    assert version == "0001_initial_schema"
    lowered = sql_text.lower()
    # schema_migrations is created by the runner, not the migration file.
    for table in EXPECTED_TABLES - {"schema_migrations"}:
        assert f"create table {table}" in lowered, (
            f"0001_initial_schema must declare CREATE TABLE {table}"
        )


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


def test_workbench_account_has_last_login_at_after_migrate(temp_schema_conn) -> None:
    # ADR-0144 login cutover: authenticate records last_login_at, surfaced on the
    # Supervisor Admin account list. The 0002 migration adds the column (the live
    # schema already applied 0001, so a new migration — not an edit — is required).
    conn, schema = temp_schema_conn
    run_migrations(conn)
    assert "workbench_account" in _tables_with_column(conn, schema, "last_login_at")


def test_workbench_policy_slot_seeded_with_six_placeholders(temp_schema_conn) -> None:
    # ADR-0145 knowledge-slots cutover (#43): the 0003 migration creates the
    # authoring table + history and seeds the six Required Operational Policy Slots
    # (ADR-0003) as empty placeholders, keyed by the kebab UI ids the store uses.
    conn, schema = temp_schema_conn
    run_migrations(conn)
    tables = _tables_in(conn, schema)
    assert {"workbench_policy_slot", "workbench_policy_slot_history"} <= tables
    with conn.cursor() as cur:
        cur.execute(
            "SELECT slot_id, status FROM workbench_policy_slot ORDER BY sort_order"
        )
        rows = cur.fetchall()
    assert [r[0] for r in rows] == [
        "business-hours",
        "payment-methods",
        "order-delivery",
        "accounting-inquiry",
        "returns-exchanges",
        "exception-scripts",
    ]
    assert all(status == "empty" for _, status in rows)


def test_eval_run_has_governance_overlay_columns_after_migrate(temp_schema_conn) -> None:
    # ADR-0146 eval-runs cutover (#44): the 0004 migration adds the overlapping
    # governance flags (signed_off, promoted -- a single status column could not
    # hold both) and the slot_key publish bridge. The live schema already applied
    # 0001-0003, so a new migration, not an edit.
    conn, schema = temp_schema_conn
    run_migrations(conn)
    for column in ("signed_off", "promoted", "slot_key"):
        assert "eval_run" in _tables_with_column(conn, schema, column), (
            f"eval_run must carry {column} after migrate (ADR-0146)"
        )


def test_retention_timestamp_columns_present(temp_schema_conn) -> None:
    conn, schema = temp_schema_conn
    run_migrations(conn)
    with_created = _tables_with_column(conn, schema, "created_at")
    # Retention is enforced off created_at on these classes (ADR-0004/0116).
    for table in ("cases", "message_turn", "workbench_audit_log", "customer_memory_slot"):
        assert table in with_created, f"{table} must carry created_at for retention"
