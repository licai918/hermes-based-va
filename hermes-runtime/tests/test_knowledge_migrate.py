"""Tests for the knowledge-store migration runner (FR-1, PRD §7.4).

Static tests (schema declaration, isolation from the business migration path)
always run. Live-DB tests run against the docker-compose Postgres at
``KNOWLEDGE_DATABASE_URL``, isolated in a throwaway schema, and **skip** (not
fail) when no Postgres is reachable -- see ``temp_knowledge_schema_conn`` in
conftest.py.
"""

from __future__ import annotations

import hermes_runtime.datastore.migrate as business_migrate
from hermes_runtime.knowledge.migrate import discover_migrations, run_migrations


def _columns(conn, schema: str, table: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = %s AND table_name = %s",
            (schema, table),
        )
        return {row[0] for row in cur.fetchall()}


def _tables_in(conn, schema: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            (schema,),
        )
        return {row[0] for row in cur.fetchall()}


# --- static (no DB needed) -------------------------------------------------


def test_discover_migrations_is_ordered_and_nonempty() -> None:
    migrations = discover_migrations()
    assert migrations, "expected at least one .sql migration on disk"
    versions = [version for version, _ in migrations]
    assert versions == sorted(versions), "migrations must apply in lexical order"
    assert versions[0] == "0001_knowledge_chunk"


def test_first_migration_declares_knowledge_chunk_with_generated_tsv_and_gin() -> None:
    version, sql_text = discover_migrations()[0]
    assert version == "0001_knowledge_chunk"
    lowered = sql_text.lower()
    assert "create table knowledge_chunk" in lowered
    assert "tsvector" in lowered
    assert "generated always as" in lowered  # generated tsv column, not app-written
    assert "using gin" in lowered
    assert "embedding" in lowered  # storage decision documented in the migration


def test_knowledge_migrations_live_in_their_own_directory_not_the_business_one() -> None:
    # Own migration path (implementer choice, stated in the S06 report): a
    # separate directory + its own 0001-based numbering, not a shared sequence
    # with hermes-runtime/migrations/.
    from hermes_runtime.knowledge.migrate import MIGRATIONS_DIR as knowledge_dir

    business_dir = business_migrate.MIGRATIONS_DIR
    assert knowledge_dir != business_dir
    assert knowledge_dir.name == "knowledge_migrations"
    assert business_dir not in knowledge_dir.parents
    assert knowledge_dir not in business_dir.parents


def test_business_migrations_never_declare_knowledge_chunk() -> None:
    # Isolation invariant (S-ISO): the business datastore's own migration path
    # must never grow a knowledge_chunk table -- that would defeat the whole
    # point of a separate database.
    for _version, sql_text in business_migrate.discover_migrations():
        assert "knowledge_chunk" not in sql_text.lower()


# --- live DB (skips if unreachable) -----------------------------------------


def test_migrations_create_knowledge_chunk_with_expected_columns(
    temp_knowledge_schema_conn,
) -> None:
    conn, schema = temp_knowledge_schema_conn
    applied = run_migrations(conn)
    assert "0001_knowledge_chunk" in applied
    assert "knowledge_chunk" in _tables_in(conn, schema)
    expected = {
        "id",
        "page_id",
        "page_type",
        "title",
        "url",
        "chunk_index",
        "chunk_text",
        "embedding",
        "tsv",
        "created_at",
    }
    assert expected <= _columns(conn, schema, "knowledge_chunk")


def test_migrations_are_idempotent(temp_knowledge_schema_conn) -> None:
    conn, _ = temp_knowledge_schema_conn
    first = run_migrations(conn)
    assert first, "first run should apply at least one migration"
    second = run_migrations(conn)
    assert second == [], "second run must be a no-op (nothing pending)"


def test_tsv_is_gin_indexed(temp_knowledge_schema_conn) -> None:
    conn, schema = temp_knowledge_schema_conn
    run_migrations(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT indexdef FROM pg_indexes"
            " WHERE schemaname = %s AND tablename = 'knowledge_chunk'",
            (schema,),
        )
        indexdefs = " ".join(row[0].lower() for row in cur.fetchall())
    assert "using gin" in indexdefs
    assert "tsv" in indexdefs


def test_knowledge_chunk_full_text_search_finds_a_row(temp_knowledge_schema_conn) -> None:
    conn, _ = temp_knowledge_schema_conn
    run_migrations(conn)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO knowledge_chunk (page_id, page_type, title, url, chunk_index, chunk_text)"
            " VALUES ('p1', 'policy', 'Return Policy', 'https://example.test/returns', 0,"
            " 'Tires may be returned within 30 days of purchase.')"
        )
        conn.commit()
        cur.execute(
            "SELECT title FROM knowledge_chunk WHERE tsv @@ plainto_tsquery('english', %s)",
            ("return tires",),
        )
        rows = cur.fetchall()
    assert rows == [("Return Policy",)]


def test_business_database_has_no_knowledge_chunk_table(
    temp_schema_conn, temp_knowledge_schema_conn
) -> None:
    # S-ISO: migrating the knowledge DB must never touch the business DB. Both
    # fixtures connect to their own DSN (KNOWLEDGE_DATABASE_URL vs
    # DATABASE_URL) -- migrate the knowledge schema, then assert the business
    # schema (a completely separate connection, possibly a separate database
    # entirely) never picked up a knowledge_chunk table.
    knowledge_conn, knowledge_schema = temp_knowledge_schema_conn
    run_migrations(knowledge_conn)
    assert "knowledge_chunk" in _tables_in(knowledge_conn, knowledge_schema)

    business_conn, business_schema = temp_schema_conn
    assert "knowledge_chunk" not in _tables_in(business_conn, business_schema)
