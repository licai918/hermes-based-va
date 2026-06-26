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

    # The queue filter is the BFF's {statuses, assignee} shape (ADR-0141), not a
    # singular status. Absent statuses default to open/in_progress, so the default
    # queue hides the resolved case (ADR-0079).
    default_ids = {
        c["case_id"]
        for c in _run(driver, "toee_workbench_read", "list_cases", {}).data["cases"]
    }
    assert a in default_ids
    assert b not in default_ids

    # An explicit statuses list including resolved surfaces both cases.
    all_ids = {
        c["case_id"]
        for c in _run(
            driver,
            "toee_workbench_read",
            "list_cases",
            {"statuses": ["open", "in_progress", "resolved"]},
        ).data["cases"]
    }
    assert {a, b} <= all_ids

    # Narrowing to resolved returns the resolved case but not the open one.
    resolved_ids = {
        c["case_id"]
        for c in _run(
            driver, "toee_workbench_read", "list_cases", {"statuses": ["resolved"]}
        ).data["cases"]
    }
    assert b in resolved_ids
    assert a not in resolved_ids


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


def test_claim_and_assign_transition_open_to_in_progress(datastore) -> None:
    # Parity with store.ts claimCase/assignCase (Slice 35 cutover): claiming or
    # assigning an *open* case moves it to in_progress, so the API path matches the
    # in-memory store the BFF mirrors.
    driver, _, _ = datastore
    case_a = _run(driver, "toee_case", "create_case", {"contact_reason": "a"}).data["case_id"]
    claimed = _run(
        driver, "toee_case_manage", "claim_case", {"case_id": case_a},
        _ctx(user_id="acct_1"),
    )
    assert claimed.data["case"]["status"] == "in_progress"
    assert claimed.data["case"]["assignee_account_id"] == "acct_1"

    case_b = _run(driver, "toee_case", "create_case", {"contact_reason": "b"}).data["case_id"]
    assigned = _run(
        driver, "toee_case_manage", "assign_case",
        {"case_id": case_b, "assignee_id": "acct_2"}, _ctx(user_id="acct_sup"),
    )
    assert assigned.data["case"]["status"] == "in_progress"
    assert assigned.data["case"]["assignee_account_id"] == "acct_2"


def test_case_mutations_return_the_fresh_read_model(datastore) -> None:
    # Each governed mutation returns the full WorkbenchCase read model so the BFF
    # cutover renders the updated case without a second get_case round-trip.
    driver, _, _ = datastore
    case_id = _run(driver, "toee_case", "create_case", {"contact_reason": "x"}).data["case_id"]

    pr = _run(
        driver, "toee_case_manage", "update_priority",
        {"case_id": case_id, "priority": "urgent"}, _ctx(user_id="a"),
    )
    assert pr.data["case"]["urgent"] is True

    cr = _run(
        driver, "toee_case_manage", "update_contact_reason",
        {"case_id": case_id, "contact_reason": "warranty"}, _ctx(user_id="a"),
    )
    assert cr.data["case"]["contact_reason"] == "warranty"

    rs = _run(
        driver, "toee_case_manage", "resolve_case", {"case_id": case_id},
        _ctx(user_id="a"),
    )
    assert rs.data["case"]["status"] == "resolved"
    assert rs.data["case"]["resolved_by_account_id"] == "a"


def test_unknown_datastore_tool_is_governed_configuration_missing(datastore) -> None:
    # A catalog-valid tool the datastore driver does not implement is a governed
    # failure (mirrors MockDriver), never a raise that escapes dispatch.
    driver, _, _ = datastore
    result = _run(driver, "toee_copilot_draft", "draft_sms", {})
    assert not result.ok
    assert result.error_class == "configuration_missing"


def test_governed_case_write_requires_an_actor(datastore) -> None:
    # I1 (ADR-0141 fail-closed actor): the cutover's whole point is actor-attributed
    # governed writes, so a toee_case_manage write with NO actor must be a governed
    # denial — no mutation, no NULL-actor audit row — never a silent 200. Covers
    # claim (the actor IS the mutation source) and assign (actor is audit-only; the
    # assignee still rides the body), the two distinct shapes among the five writes.
    driver, _, _ = datastore
    case_id = _run(driver, "toee_case", "create_case", {"contact_reason": "x"}).data[
        "case_id"
    ]

    claim = _run(driver, "toee_case_manage", "claim_case", {"case_id": case_id})
    assert not claim.ok
    assert claim.error_class == "policy_blocked"

    assign = _run(
        driver,
        "toee_case_manage",
        "assign_case",
        {"case_id": case_id, "assignee_id": "acct_2"},
    )
    assert not assign.ok
    assert assign.error_class == "policy_blocked"

    # Neither denied write mutated the case...
    case = _run(driver, "toee_workbench_read", "get_case", {"case_id": case_id}).data[
        "case"
    ]
    assert case["assignee_account_id"] is None
    assert case["status"] == "open"
    # ...nor wrote any audit row (a NULL-actor governed audit is exactly what I1 bans).
    entries = _run(
        driver, "toee_workbench_read", "get_audit_log", {"case_id": case_id}
    ).data["entries"]
    assert entries == []


def test_claim_is_atomic_no_silent_steal_and_idempotent(datastore) -> None:
    # I2 (ADR-0079): the claim conflict guard lives in SQL, not a check-then-act
    # pre-read. Account A claims an unassigned case and gets it (assignee=A,
    # in_progress); a second claim by B on the now-A-held case is a governed
    # conflict — no last-write-wins steal — and writes no audit row; A re-claiming
    # its own case stays idempotent.
    driver, _, _ = datastore
    case_id = _run(driver, "toee_case", "create_case", {"contact_reason": "x"}).data[
        "case_id"
    ]

    first = _run(
        driver, "toee_case_manage", "claim_case", {"case_id": case_id},
        _ctx(user_id="acct_a"),
    )
    assert first.ok
    assert first.data["case"]["assignee_account_id"] == "acct_a"
    assert first.data["case"]["status"] == "in_progress"

    steal = _run(
        driver, "toee_case_manage", "claim_case", {"case_id": case_id},
        _ctx(user_id="acct_b"),
    )
    assert not steal.ok
    assert steal.error_class == "conflict"

    # B neither stole the case nor wrote a claim audit row.
    case = _run(driver, "toee_workbench_read", "get_case", {"case_id": case_id}).data[
        "case"
    ]
    assert case["assignee_account_id"] == "acct_a"
    audit = _run(
        driver, "toee_workbench_read", "get_audit_log", {"case_id": case_id}
    ).data["entries"]
    claim_actors = [e["account_id"] for e in audit if e["action"] == "claim_case"]
    assert claim_actors == ["acct_a"]

    again = _run(
        driver, "toee_case_manage", "claim_case", {"case_id": case_id},
        _ctx(user_id="acct_a"),
    )
    assert again.ok
    assert again.data["case"]["assignee_account_id"] == "acct_a"


def test_claim_missing_case_is_governed_not_found(datastore) -> None:
    # I2: a claim on a non-existent case is a governed not_found (the BFF maps it to
    # 404, store-path CASE_NOT_FOUND parity), distinct from the held-by-another
    # conflict, so rowcount 0 is classified rather than swallowed.
    driver, _, _ = datastore
    res = _run(
        driver, "toee_case_manage", "claim_case", {"case_id": "case_missing"},
        _ctx(user_id="acct_a"),
    )
    assert not res.ok
    assert res.error_class == "not_found"
