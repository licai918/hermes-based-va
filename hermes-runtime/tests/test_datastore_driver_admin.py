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

    listed = _run(driver, "toee_workbench_admin", "list_accounts", {})
    assert any(a["username"] == "rep1" for a in listed.data["accounts"])
    # password hashes never leave the datastore handler.
    assert all("password_hash" not in a for a in listed.data["accounts"])

    updated = _run(
        driver, "toee_workbench_admin", "update_account_role",
        {"account_id": account_id, "role": "supervisor_admin"},
    )
    assert updated.data["role"] == "supervisor_admin"

    disabled = _run(
        driver, "toee_workbench_admin", "disable_account", {"account_id": account_id}
    )
    assert disabled.data["disabled"] is True

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


def test_create_account_requires_fields(datastore) -> None:
    driver, _, _ = datastore
    result = _run(driver, "toee_workbench_admin", "create_account", {"role": "r"})
    assert not result.ok
    assert result.error_class == "unexpected_error"


def test_duplicate_username_is_governed(datastore) -> None:
    driver, _, _ = datastore
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
    assert second.error_class == "unexpected_error"


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
