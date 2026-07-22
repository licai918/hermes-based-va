"""Dev bootstrap migration (0005_dev_bootstrap): local Tier B seed data.

After migrate, workbench accounts and demo cases exist without manual SQL. Skip-if-
no-DB via the shared ``temp_schema_conn`` fixture (ADR-0142).
"""

from __future__ import annotations

import json

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


def test_dev_bootstrap_accounts_carry_the_lockout_policy(temp_schema_conn) -> None:
    """The seeded dev accounts are subject to ADR-0018 server-side (0.0.4 S08).

    Seeding and lockout used to be two halves of the same TS file
    (apps/workbench/lib/auth/account-store.ts). 0.0.4 S09 deletes it, so the
    seeded accounts must arrive with the policy already attached here: five wrong
    passwords lock ``rep`` out, and the correct password no longer helps.
    """
    conn, _ = temp_schema_conn
    run_migrations(conn)

    from hermes_runtime.datastore.driver import PostgresDriver

    driver = PostgresDriver(connection=conn)

    def attempt(password: str):
        return execute_tool(
            tool="toee_workbench_admin",
            action="authenticate",
            params={"username": "rep", "password": password},
            context=_admin_ctx(),
            driver=driver,
        )

    for _ in range(5):
        assert attempt("wrong-password").error_class == "unauthenticated"

    locked = attempt(DEV_SEED_PASSWORD)
    assert not locked.ok
    assert locked.error_class == "locked"  # BFF -> 423

    # And the seed hash itself is untouched: clearing the window restores login,
    # so the dev credentials keep working for the owner's local login.
    with conn.cursor() as cur:
        cur.execute("UPDATE workbench_account SET locked_until = NULL WHERE username = 'rep'")
    conn.commit()
    assert attempt(DEV_SEED_PASSWORD).ok


def test_seeded_account_logs_in_and_locks_out_over_the_dispatch_wire(
    temp_schema_conn,
) -> None:
    """Acceptance ①: a seeded account logs in via the API path the BFF actually uses.

    The unit tests above call the handler through ``execute_tool`` in-process. This
    one goes over ``POST /v1/tools:dispatch`` — bearer auth, supervisor_admin
    allowlist, JSON envelope — because that wire is where the workbench will live
    once S09 removes the in-memory fallback. The assertion that matters is the
    error CLASS on the envelope: the governed message is replaced upstream, so the
    class is the only thing that can tell the login form "locked" (423) apart from
    "bad password" (401). If ``locked`` did not survive serialization here, the BFF
    would render the wrong message and nothing else would notice.
    """
    from starlette.testclient import TestClient

    from hermes_runtime.datastore.driver import PostgresDriver
    from hermes_runtime.tool_dispatch_app import create_tool_dispatch_app

    conn, _ = temp_schema_conn
    run_migrations(conn)

    token = "test-admin-api-token"
    client = TestClient(
        create_tool_dispatch_app(
            api_token=token,
            profile="supervisor_admin",
            driver=PostgresDriver(connection=conn),
        )
    )

    def login(password: str):
        response = client.post(
            "/v1/tools:dispatch",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "tool": "toee_workbench_admin",
                "action": "authenticate",
                "params": {"username": "supervisor", "password": password},
            },
        )
        assert response.status_code == 200  # governed failures ride a 200 body
        return response.json()

    good = login(DEV_SEED_PASSWORD)
    assert good["ok"] is True
    assert good["data"]["account"]["username"] == "supervisor"
    assert good["data"]["account"]["role"] == "workbench_supervisor"
    assert "password_hash" not in json.dumps(good)

    for _ in range(5):
        bad = login("nope-not-it")
        assert bad["ok"] is False
        assert bad["error"]["class"] == "unauthenticated"

    locked = login(DEV_SEED_PASSWORD)
    assert locked["ok"] is False
    assert locked["error"]["class"] == "locked"  # BFF -> 423, LoginForm lockout copy


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
