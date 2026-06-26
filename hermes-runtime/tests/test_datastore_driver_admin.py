"""Slice 33 / #36: Postgres-backed Supervisor Admin governance tools.

Covers ``toee_workbench_admin`` (accounts, ADR-0069/0089), ``toee_knowledge_ops``
(policy-slot versions, ADR-0003/0040), and ``toee_eval_review`` (eval runs,
ADR-0074/0088) doing real CRUD with governance audit writes. Skip-if-no-DB.
"""

from __future__ import annotations

import uuid

from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext


def _run(driver, tool, action, params, user_id="acct_admin"):
    return execute_tool(
        tool=tool,
        action=action,
        params=params,
        context=ToolExecutionContext(profile="supervisor_admin", user_id=user_id),
        driver=driver,
    )


def _audit_actions(conn, target_type, target_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT action FROM workbench_audit_log WHERE target_type = %s AND target_id = %s",
            (target_type, target_id),
        )
        return [r[0] for r in cur.fetchall()]


def _audit_actor(conn, target_type, target_id, action):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT account_id FROM workbench_audit_log"
            " WHERE target_type = %s AND target_id = %s AND action = %s",
            (target_type, target_id, action),
        )
        row = cur.fetchone()
    return row[0] if row else None


# --- accounts ---------------------------------------------------------------


def test_account_crud_with_audit(datastore) -> None:
    driver, conn, _ = datastore
    created = _run(
        driver, "toee_workbench_admin", "create_account",
        {"username": "rep1", "password_hash": "hash", "role": "customer_service_rep"},
    )
    assert created.ok
    assert created.data["created"] is True
    account_id = created.data["account_id"]
    # The mutation returns the fresh account read model so the BFF renders it
    # without a second round-trip (store-path parity); the password hash never
    # rides that row.
    acct = created.data["account"]
    assert acct["account_id"] == account_id
    assert acct["username"] == "rep1"
    assert acct["role"] == "customer_service_rep"
    assert acct["status"] == "active"
    assert "password_hash" not in acct

    listed = _run(driver, "toee_workbench_admin", "list_accounts", {})
    assert any(a["username"] == "rep1" for a in listed.data["accounts"])
    # password hashes never leave the datastore handler.
    assert all("password_hash" not in a for a in listed.data["accounts"])

    updated = _run(
        driver, "toee_workbench_admin", "update_account_role",
        {"account_id": account_id, "role": "supervisor_admin"},
    )
    assert updated.data["role"] == "supervisor_admin"
    assert updated.data["account"]["role"] == "supervisor_admin"

    disabled = _run(
        driver, "toee_workbench_admin", "disable_account", {"account_id": account_id}
    )
    assert disabled.data["disabled"] is True
    assert disabled.data["account"]["status"] == "disabled"

    row = next(
        a for a in _run(driver, "toee_workbench_admin", "list_accounts", {}).data["accounts"]
        if a["id"] == account_id
    )
    assert row["role"] == "supervisor_admin"
    assert row["status"] == "disabled"

    actions = _audit_actions(conn, "account", account_id)
    assert "create_account" in actions
    assert "update_account_role" in actions
    assert "disable_account" in actions
    # Audit is attributed to the acting account (ADR-0029/0141), not NULL.
    assert _audit_actor(conn, "account", account_id, "create_account") == "acct_admin"
    assert _audit_actor(conn, "account", account_id, "disable_account") == "acct_admin"


def test_create_account_requires_fields(datastore) -> None:
    driver, _, _ = datastore
    result = _run(driver, "toee_workbench_admin", "create_account", {"role": "r"})
    assert not result.ok
    assert result.error_class == "unexpected_error"


def test_duplicate_username_is_governed(datastore) -> None:
    # Uniqueness is enforced atomically in SQL (ON CONFLICT), so a duplicate
    # username is a governed `conflict` (BFF maps to 409, store-path parity), not a
    # raw unique-violation surfaced as unexpected_error.
    driver, conn, _ = datastore
    name = f"dup_{uuid.uuid4().hex[:6]}"
    first = _run(
        driver, "toee_workbench_admin", "create_account",
        {"username": name, "password_hash": "h", "role": "r"},
    )
    assert first.ok
    second = _run(
        driver, "toee_workbench_admin", "create_account",
        {"username": name, "password_hash": "h2", "role": "r"},
    )
    assert not second.ok
    assert second.error_class == "conflict"
    # The rejected create left exactly one account + one create_account audit row.
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM workbench_account WHERE username = %s", (name,))
        assert cur.fetchone()[0] == 1
        cur.execute(
            "SELECT count(*) FROM workbench_audit_log WHERE action = 'create_account'"
            " AND target_id = %s",
            (first.data["account_id"],),
        )
        assert cur.fetchone()[0] == 1


def test_account_writes_require_actor(datastore) -> None:
    # I1 (ADR-0141 fail-closed actor): a governed admin write with NO actor is a
    # governed denial — no row, no NULL-actor audit — never a silent success. Every
    # admin mutation (create/update/disable) is guarded at this one boundary.
    driver, conn, _ = datastore
    res = _run(
        driver, "toee_workbench_admin", "create_account",
        {"username": "ghostmaker", "password_hash": "h", "role": "customer_service_rep"},
        user_id=None,
    )
    assert not res.ok
    assert res.error_class == "policy_blocked"
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM workbench_account WHERE username = %s", ("ghostmaker",))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM workbench_audit_log WHERE action = 'create_account'")
        assert cur.fetchone()[0] == 0

    # An account created *with* an actor is the target for the update/disable checks.
    account_id = _run(
        driver, "toee_workbench_admin", "create_account",
        {"username": "realacct", "password_hash": "h", "role": "customer_service_rep"},
    ).data["account_id"]

    upd = _run(
        driver, "toee_workbench_admin", "update_account_role",
        {"account_id": account_id, "role": "workbench_admin"}, user_id=None,
    )
    assert not upd.ok
    assert upd.error_class == "policy_blocked"
    dis = _run(
        driver, "toee_workbench_admin", "disable_account",
        {"account_id": account_id}, user_id=None,
    )
    assert not dis.ok
    assert dis.error_class == "policy_blocked"
    # The denied actor-less writes mutated nothing and wrote no audit row: the
    # account keeps its created role + active status, and only create_account logged.
    assert _audit_actions(conn, "account", account_id) == ["create_account"]
    row = next(
        a for a in _run(driver, "toee_workbench_admin", "list_accounts", {}).data["accounts"]
        if a["id"] == account_id
    )
    assert row["role"] == "customer_service_rep"
    assert row["status"] == "active"


def test_update_or_disable_missing_account_is_not_found(datastore) -> None:
    # A governed write against a missing account is a governed not_found (BFF maps
    # to 404, store-path "account not found" parity), not an unexpected_error 502.
    driver, _, _ = datastore
    upd = _run(
        driver, "toee_workbench_admin", "update_account_role",
        {"account_id": "acct_ghost", "role": "workbench_admin"},
    )
    assert not upd.ok
    assert upd.error_class == "not_found"
    dis = _run(
        driver, "toee_workbench_admin", "disable_account", {"account_id": "acct_ghost"}
    )
    assert not dis.ok
    assert dis.error_class == "not_found"


# --- knowledge ops ----------------------------------------------------------


def test_policy_slots_overlay_stored_versions(datastore) -> None:
    driver, _, _ = datastore
    # All six Required Operational Policy Slots are always present (ADR-0003).
    slots = _run(driver, "toee_knowledge_ops", "get_policy_slots", {}).data["slots"]
    keys = {s["key"] for s in slots}
    assert "business_hours_service_boundaries" in keys
    assert len(slots) == 6
    boundary = next(s for s in slots if s["key"] == "business_hours_service_boundaries")
    assert boundary["status"] == "empty"

    # A draft version overlays the placeholder.
    upd = _run(
        driver, "toee_knowledge_ops", "update_policy_slot",
        {"slot": "business_hours_service_boundaries", "content": "Mon-Fri 8-5"},
    )
    assert upd.data["state"] == "draft"

    slots = _run(driver, "toee_knowledge_ops", "get_policy_slots", {}).data["slots"]
    boundary = next(s for s in slots if s["key"] == "business_hours_service_boundaries")
    assert boundary["status"] == "draft"
    assert boundary["content"] == "Mon-Fri 8-5"


def test_policy_slot_lifecycle_submit_then_promote(datastore) -> None:
    driver, conn, _ = datastore
    slot = "payment_payment_link_rules"
    _run(driver, "toee_knowledge_ops", "update_policy_slot", {"slot": slot, "content": "links only"})
    submitted = _run(driver, "toee_knowledge_ops", "submit_for_eval", {"slot": slot})
    assert submitted.data["status"] == "pending_eval"

    promoted = _run(driver, "toee_eval_review", "promote_pending_policy", {"slot": slot})
    assert promoted.data["promoted"] is True
    assert promoted.data["status"] == "published"

    slots = _run(driver, "toee_knowledge_ops", "get_policy_slots", {}).data["slots"]
    assert next(s for s in slots if s["key"] == slot)["status"] == "published"
    assert "update_policy_slot" in _audit_actions(conn, "policy_slot", slot)


def test_update_policy_slot_rejects_unknown_slot(datastore) -> None:
    driver, _, _ = datastore
    result = _run(driver, "toee_knowledge_ops", "update_policy_slot", {"slot": "not_a_slot", "content": "x"})
    assert not result.ok
    assert result.error_class == "unexpected_error"


# --- eval review ------------------------------------------------------------


def _seed_eval_run(conn, run_id, suite="text_first_launch", status="passed", failed_high=0):
    from psycopg.types.json import Jsonb

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO eval_run (id, suite, status, failed_high, report) VALUES (%s,%s,%s,%s,%s)",
            (run_id, suite, status, failed_high, Jsonb({})),
        )
    conn.commit()


def test_eval_review_list_get_and_sign_off(datastore) -> None:
    driver, conn, _ = datastore
    run_id = f"run_{uuid.uuid4().hex}"
    _seed_eval_run(conn, run_id, status="failed", failed_high=0)

    listed = _run(driver, "toee_eval_review", "list_eval_runs", {})
    assert any(r["id"] == run_id for r in listed.data["runs"])

    got = _run(driver, "toee_eval_review", "get_eval_run", {"run_id": run_id})
    assert got.data["run"]["id"] == run_id
    assert got.data["run"]["status"] == "failed"

    signed = _run(driver, "toee_eval_review", "sign_off_medium_failure", {"run_id": run_id})
    assert signed.data["signed_off"] is True

    got = _run(driver, "toee_eval_review", "get_eval_run", {"run_id": run_id})
    assert got.data["run"]["status"] == "signed_off"
