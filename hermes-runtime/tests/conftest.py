"""Shared fixtures for hermes-runtime datastore integration tests.

These talk to the docker-compose Postgres at ``DATABASE_URL`` and isolate each
test in a throwaway schema, so they never touch dev data and **skip** (not fail)
when no Postgres is reachable (ADR-0142 local-first).
"""

from __future__ import annotations

import uuid

import pytest

from hermes_runtime.datastore.config import database_url
from hermes_runtime.datastore.migrate import DEV_ONLY_MIGRATIONS, run_migrations

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
    # Skip the LOCAL DEV ONLY seed: its demo cases (case_ar_urgent, case_toolfail)
    # would pollute these isolated schemas. Tests that need the seed use
    # temp_schema_conn + run_migrations() directly (see test_datastore_dev_bootstrap.py).
    run_migrations(conn, exclude=DEV_ONLY_MIGRATIONS)
    from hermes_runtime.datastore.driver import PostgresDriver

    return PostgresDriver(connection=conn), conn, schema


@pytest.fixture(autouse=True)
def _reset_tool_registry():
    """Snapshot/restore the shared upstream ``tools.registry`` singleton per test.

    ``boot_profile`` (hermes_runtime/boot.py) and Hermes' own native
    ``discover_plugins`` (test_entrypoint_discovery.py) register tool handlers
    into a PROCESS-WIDE singleton (``tools.registry.registry``) keyed by tool
    name. A profile's static ``(name, toolset)`` pairs never change, so a later
    boot always silently overwrites an earlier one for the same name -- and,
    more perniciously, entries NO later boot happens to touch just accumulate
    forever. ``run_agent_turn`` (hermes_runtime/live.py) unions a booted
    profile's own tool names with the agent's own DEFAULT ``valid_tool_names``,
    which is resolved from whatever toolsets are CURRENTLY registered -- so a
    tool an earlier test registered for a DIFFERENT profile (e.g. the External
    profile's ``toee_textline_reply__send_message``, registered globally by
    test_entrypoint_discovery.py's in-process ``discover_plugins(force=True)``)
    can silently satisfy the "is this tool allowed" check in a LATER test that
    boots a profile without it -- defeating the very rejection the later test
    means to prove.

    Confirmed live: ``pytest tests/test_entrypoint_discovery.py
    tests/test_copilot_turn.py`` fails
    ``test_a_send_tool_call_is_rejected_under_the_real_multistep_loop`` and
    ``test_a_send_tool_call_is_rejected_in_a_chat_turn_under_the_real_loop``
    without this fixture (the scripted send tool_call actually dispatches
    instead of getting the intended "does not exist" rejection). Both are
    order-independent green with it, and a full-suite run in reverse file
    order (a controlled A/B: identical otherwise) fails only those two tests
    without this fixture and neither with it.

    Restoring the exact pre-test snapshot after each test -- rather than
    clearing the registry outright -- keeps process-lifetime registrations
    (Hermes' own built-in tools, registered exactly once via
    ``model_tools.discover_builtin_tools()`` at first import) intact, since
    they are already present in every test's "before" snapshot.
    """
    from tools.registry import registry

    with registry._lock:
        tools_snapshot = dict(registry._tools)
        checks_snapshot = dict(registry._toolset_checks)
        aliases_snapshot = dict(registry._toolset_aliases)
    yield
    with registry._lock:
        registry._tools = tools_snapshot
        registry._toolset_checks = checks_snapshot
        registry._toolset_aliases = aliases_snapshot
        registry._generation += 1
