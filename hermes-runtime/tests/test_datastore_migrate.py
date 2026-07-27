"""Integration tests for the local Toee Business Datastore migration runner.

Slice 32 / #35 (ADR-0140 system-of-record, ADR-0142 local-first). These run
against the docker-compose Postgres at ``DATABASE_URL`` and are isolated in a
throwaway schema so they never touch dev data. They **skip** (not fail) when no
Postgres is reachable, so the suite stays green without a database; CI gets a
Postgres service container in a later slice.
"""

from __future__ import annotations

from hermes_runtime.datastore.migrate import (
    DEV_ONLY_MIGRATIONS,
    discover_migrations,
    migrate_exclusions,
    run_migrations,
)

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


def test_migration_numeric_prefixes_are_unique() -> None:
    """Two migrations may never share a numeric prefix.

    The ledger keys on the full file stem, so a duplicate prefix does NOT break
    the runner -- both files apply, each gets its own ``schema_migrations`` row.
    That is exactly why it slips through: the failure is silent. It has now
    happened twice, both times when two branches numbered concurrently and git
    merged them without a conflict (the filenames differ after the prefix, so
    there is nothing for git to flag): 0008 (agent_experience vs the first draft
    of inbound_event_claim) and 0011 (job_queue vs inbound_event_claim). Each
    cost a renumber after the fact.

    The ordering assertion above passes with duplicates present, so this is the
    guard that actually catches it -- at PR time, with no database required.
    """
    versions = [version for version, _ in discover_migrations()]
    by_prefix: dict[str, list[str]] = {}
    for version in versions:
        by_prefix.setdefault(version.split("_", 1)[0], []).append(version)
    duplicates = {
        prefix: names for prefix, names in by_prefix.items() if len(names) > 1
    }
    assert not duplicates, (
        "migrations must not share a numeric prefix; renumber the newer one to "
        f"the next free number and make its DDL idempotent: {duplicates}"
    )


def test_renumbered_job_queue_migration_is_replay_safe(temp_schema_conn) -> None:
    """The job-queue migration's DDL must survive being executed twice.

    It shipped as 0011 and was renumbered to 0014 (0011 collided with
    0011_inbound_event_claim). The ledger keys on the full file stem, so to a
    database that already applied ``0011_job_queue`` the renamed file is a
    brand-new version and its DDL runs a SECOND time against a schema that
    already has the ``job`` table. Bare ``CREATE TABLE job`` raises
    DuplicateTable there and aborts the whole migrate -- which is every dev
    machine that pulled the rename.

    ``test_migrations_are_idempotent`` does NOT cover this: it proves the
    *ledger* dedupes, and never re-executes any SQL. This re-executes the
    statements directly, bypassing the ledger, which is precisely what a rename
    does.
    """
    conn, _ = temp_schema_conn
    run_migrations(conn, exclude=DEV_ONLY_MIGRATIONS)

    sql_by_version = dict(discover_migrations())
    job_queue_sql = next(
        sql for version, sql in sql_by_version.items() if version.endswith("_job_queue")
    )

    # Must not raise: this is the re-run a renumber forces.
    with conn.cursor() as cur:
        cur.execute(job_queue_sql)
    conn.commit()


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


def test_customer_memory_slot_has_actor_account_id_after_migrate(temp_schema_conn) -> None:
    # PRD 0.0.2 §9 decision 2 / FR-4: the 0007 migration adds a nullable actor
    # column so a UI correction's row can carry the rep's account id. The live
    # schema already applied 0001-0006, so a new migration, not an edit.
    conn, schema = temp_schema_conn
    run_migrations(conn)
    assert "customer_memory_slot" in _tables_with_column(conn, schema, "actor_account_id")


def test_customer_memory_actor_column_has_no_backfill_on_existing_rows(
    temp_schema_conn,
) -> None:
    # RK-6/NFR-1: nullable ALTER, no backfill -- a row written before 0007 applies
    # must read back a NULL actor, not a default. Applying 0007 against a live
    # (non-empty) table would itself raise if the column were ever NOT NULL
    # without a default, so this also pins nullability.
    conn, schema = temp_schema_conn
    run_migrations(conn, exclude={"0007_customer_memory_actor"})
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO customer_memory_slot
                (id, binding_key, binding_kind, slot_name, slot_value, source)
            VALUES ('mem_pre_0007', 'provisional:sms:+15550000000', 'provisional',
                    'channel_preference', 'sms', 'customer_explicit')
            """
        )
    conn.commit()

    run_migrations(conn)  # applies 0007 (and anything else pending) on top

    with conn.cursor() as cur:
        cur.execute(
            "SELECT actor_account_id FROM customer_memory_slot WHERE id = %s",
            ("mem_pre_0007",),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] is None


def test_retention_timestamp_columns_present(temp_schema_conn) -> None:
    conn, schema = temp_schema_conn
    run_migrations(conn)
    with_created = _tables_with_column(conn, schema, "created_at")
    # Retention is enforced off created_at on these classes (ADR-0004/0116).
    for table in ("cases", "message_turn", "workbench_audit_log", "customer_memory_slot"):
        assert table in with_created, f"{table} must carry created_at for retention"


def test_migrate_exclusions_skip_dev_seed_unless_opted_in(monkeypatch) -> None:
    # The LOCAL DEV ONLY 0005_dev_bootstrap seed must not reach cloud/prod: the
    # migrate() entrypoint excludes it by default, opted in via HERMES_APPLY_DEV_SEED.
    monkeypatch.delenv("HERMES_APPLY_DEV_SEED", raising=False)
    assert "0005_dev_bootstrap" in DEV_ONLY_MIGRATIONS
    assert DEV_ONLY_MIGRATIONS <= migrate_exclusions()

    for truthy in ("1", "true", "TRUE", "yes"):
        monkeypatch.setenv("HERMES_APPLY_DEV_SEED", truthy)
        assert "0005_dev_bootstrap" not in migrate_exclusions()

    monkeypatch.setenv("HERMES_APPLY_DEV_SEED", "0")
    assert "0005_dev_bootstrap" in migrate_exclusions()


def test_run_migrations_excluding_dev_seed_leaves_cases_empty(temp_schema_conn) -> None:
    conn, _ = temp_schema_conn
    applied = run_migrations(conn, exclude=DEV_ONLY_MIGRATIONS)
    assert "0005_dev_bootstrap" not in applied
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM cases")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM workbench_account")
        assert cur.fetchone()[0] == 0
