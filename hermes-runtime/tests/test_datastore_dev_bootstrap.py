"""Dev bootstrap migration (0005_dev_bootstrap): local Tier B seed data.

After migrate, workbench accounts and demo cases exist without manual SQL. Skip-if-
no-DB via the shared ``temp_schema_conn`` fixture (ADR-0142).
"""

from __future__ import annotations

from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

from hermes_runtime.datastore.migrate import run_migrations

DEV_SEED_PASSWORD = "Workbench123!"


def _admin_ctx(user_id: str = "seed-admin"):
    return ToolExecutionContext(profile="supervisor_admin", user_id=user_id)


def _copilot_ctx(user_id: str = "seed-rep"):
    return ToolExecutionContext(profile="internal_copilot", user_id=user_id)


def test_dev_bootstrap_seeds_accounts_and_cases(temp_schema_conn) -> None:
    conn, _ = temp_schema_conn
    applied = run_migrations(conn)
    assert "0005_dev_bootstrap" in applied

    with conn.cursor() as cur:
        cur.execute("SELECT username FROM workbench_account ORDER BY username")
        assert [row[0] for row in cur.fetchall()] == ["admin", "rep", "supervisor"]

    from hermes_runtime.datastore.driver import PostgresDriver

    driver = PostgresDriver(connection=conn)

    auth = execute_tool(
        tool="toee_workbench_admin",
        action="authenticate",
        params={"username": "rep", "password": DEV_SEED_PASSWORD},
        context=_admin_ctx(),
        driver=driver,
    )
    assert auth.ok
    assert auth.data["account"]["username"] == "rep"
    assert "password_hash" not in auth.data["account"]

    listed = execute_tool(
        tool="toee_workbench_read",
        action="list_cases",
        params={},
        context=_copilot_ctx(),
        driver=driver,
    )
    assert listed.ok
    case_ids = {c["case_id"] for c in listed.data["cases"]}
    assert {"case_ar_urgent", "case_toolfail"} <= case_ids

    urgent = next(c for c in listed.data["cases"] if c["case_id"] == "case_ar_urgent")
    assert urgent["urgent"] is True
    assert urgent["sms_session_active"] is True
    assert urgent["identity_summary"] == "Verified: Westside Auto (acct 4471) · +1 (555) 447-1471"
    assert urgent["last_message_preview"]


def test_dev_bootstrap_is_idempotent(temp_schema_conn) -> None:
    conn, _ = temp_schema_conn
    run_migrations(conn)
    second = run_migrations(conn)
    assert second == []

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM workbench_account")
        assert cur.fetchone()[0] == 3
        cur.execute("SELECT count(*) FROM cases")
        assert cur.fetchone()[0] == 2
