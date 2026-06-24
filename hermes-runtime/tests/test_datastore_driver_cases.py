"""Slice 33 / #36: Postgres-backed case handlers through ``execute_tool``.

Covers ``toee_case``, ``toee_case_manage``, and ``toee_workbench_read`` doing real
CRUD against local Postgres, plus the audit writes that must land in the datastore
(criterion 4). Skip-if-no-DB via the shared ``datastore`` fixture (ADR-0142).
"""

from __future__ import annotations

from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext


def _ctx(profile: str = "internal_copilot", user_id: str | None = None):
    return ToolExecutionContext(profile=profile, user_id=user_id)


def _run(driver, tool, action, params=None, context=None):
    return execute_tool(
        tool=tool,
        action=action,
        params=params or {},
        context=context or _ctx(),
        driver=driver,
    )


def test_create_case_persists_and_is_readable(datastore) -> None:
    driver, _, _ = datastore
    created = _run(
        driver,
        "toee_case",
        "create_case",
        {"contact_reason": "delivery_issue", "urgency": "high", "summary": "late tires"},
    )
    assert created.ok
    case_id = created.data["case_id"]
    assert created.data["status"] == "open"

    got = _run(driver, "toee_workbench_read", "get_case", {"case_id": case_id})
    assert got.ok
    case = got.data["case"]
    assert case is not None
    assert case["case_id"] == case_id
    assert case["contact_reason"] == "delivery_issue"
    assert case["urgency"] == "high"
    assert case["status"] == "open"


def test_driver_reports_datastore_kind_on_audit(datastore) -> None:
    driver, _, _ = datastore
    result = _run(driver, "toee_case", "create_case", {"contact_reason": "x"})
    assert result.ok
    # execute_tool stamps the audit record with driver.kind (ADR-0136).
    assert result.audit.driver == "datastore"


def test_get_case_missing_returns_null(datastore) -> None:
    driver, _, _ = datastore
    got = _run(driver, "toee_workbench_read", "get_case", {"case_id": "case_missing"})
    assert got.ok
    assert got.data["case"] is None


def test_list_cases_returns_created_and_filters_by_status(datastore) -> None:
    driver, _, _ = datastore
    a = _run(driver, "toee_case", "create_case", {"contact_reason": "a"}).data["case_id"]
    b = _run(driver, "toee_case", "create_case", {"contact_reason": "b"}).data["case_id"]
    _run(driver, "toee_case_manage", "resolve_case", {"case_id": b}, _ctx(user_id="acct_1"))

    listed = _run(driver, "toee_workbench_read", "list_cases", {})
    assert listed.ok
    ids = {c["case_id"] for c in listed.data["cases"]}
    assert {a, b} <= ids

    open_only = _run(driver, "toee_workbench_read", "list_cases", {"status": "open"})
    open_ids = {c["case_id"] for c in open_only.data["cases"]}
    assert a in open_ids
    assert b not in open_ids


def test_update_case_changes_urgency_and_contact_reason(datastore) -> None:
    driver, _, _ = datastore
    case_id = _run(
        driver, "toee_case", "create_case", {"contact_reason": "x", "urgency": "low"}
    ).data["case_id"]

    upd = _run(
        driver,
        "toee_case",
        "update_case",
        {"case_id": case_id, "urgency": "high", "contact_reason": "delivery_issue"},
    )
    assert upd.ok
    assert upd.data["urgency"] == "high"

    case = _run(driver, "toee_workbench_read", "get_case", {"case_id": case_id}).data["case"]
    assert case["urgency"] == "high"
    assert case["contact_reason"] == "delivery_issue"


def test_case_manage_mutations_persist_and_write_audit(datastore) -> None:
    driver, _, _ = datastore
    case_id = _run(driver, "toee_case", "create_case", {"contact_reason": "x"}).data["case_id"]

    assert _run(
        driver, "toee_case_manage", "claim_case", {"case_id": case_id},
        _ctx(user_id="acct_claimer"),
    ).data["claimed"] is True
    assigned = _run(
        driver, "toee_case_manage", "assign_case",
        {"case_id": case_id, "assignee_id": "acct_2"}, _ctx(user_id="acct_supervisor"),
    )
    assert assigned.data["assignee_id"] == "acct_2"
    resolved = _run(
        driver, "toee_case_manage", "resolve_case", {"case_id": case_id},
        _ctx(user_id="acct_supervisor"),
    )
    assert resolved.data["status"] == "resolved"

    case = _run(driver, "toee_workbench_read", "get_case", {"case_id": case_id}).data["case"]
    assert case["status"] == "resolved"
    assert case["assignee_account_id"] == "acct_2"
    assert case["resolved_by_account_id"] == "acct_supervisor"

    # Criterion 4: every governed mutation appended an audit row in the datastore.
    audit = _run(driver, "toee_workbench_read", "get_audit_log", {"case_id": case_id})
    assert audit.ok
    actions = [e["action"] for e in audit.data["entries"]]
    assert "claim_case" in actions
    assert "assign_case" in actions
    assert "resolve_case" in actions
    entry = next(e for e in audit.data["entries"] if e["action"] == "assign_case")
    assert entry["account_id"] == "acct_supervisor"
    assert entry["profile"] == "internal_copilot"
    assert entry["target_id"] == case_id


def test_unknown_datastore_tool_is_governed_configuration_missing(datastore) -> None:
    # A catalog-valid tool the datastore driver does not implement is a governed
    # failure (mirrors MockDriver), never a raise that escapes dispatch.
    driver, _, _ = datastore
    result = _run(driver, "toee_copilot_draft", "draft_sms", {})
    assert not result.ok
    assert result.error_class == "configuration_missing"
