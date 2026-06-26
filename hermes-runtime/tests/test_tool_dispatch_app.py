"""Per-profile tool-dispatch HTTP API (ADR-0141).

The deterministic half of the per-profile Hermes surface the workbench BFF calls:
``POST /v1/tools:dispatch`` runs the same governed ``execute_tool`` the channel
pipeline uses — no LLM — under one fixed profile. Bearer auth gates the route; the
Profile Tool Allowlist (ADR-0034/0035/0038) is enforced as a Tool Gate, so a tool
outside the profile comes back as a governed ``{"error": ...}`` (ADR-0020), never a
raised exception. Tool Gate denials are HTTP 200 governed JSON; only auth/shape
problems are 4xx.
"""

from __future__ import annotations

from starlette.testclient import TestClient

from hermes_runtime.tool_dispatch_app import create_tool_dispatch_app

API_TOKEN = "test-copilot-api-token"


def _client(profile: str = "internal_copilot") -> TestClient:
    return TestClient(create_tool_dispatch_app(api_token=API_TOKEN, profile=profile))


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


class _CapturingDriver:
    """Records the ToolExecutionContext the dispatch app builds for execute_tool."""

    kind = "mock"

    def __init__(self) -> None:
        self.context = None

    def execute(self, request, context):  # noqa: ANN001 (ToolDriver signature)
        self.context = context
        return {"ok": True}


def _client_with_driver(driver, profile: str = "internal_copilot") -> TestClient:
    return TestClient(
        create_tool_dispatch_app(api_token=API_TOKEN, profile=profile, driver=driver)
    )


def test_healthz_returns_ok() -> None:
    response = _client().get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dispatch_requires_bearer_token() -> None:
    # No Authorization header → 401; the tool never runs (fail-closed, ADR-0106).
    response = _client().post(
        "/v1/tools:dispatch",
        json={"tool": "toee_workbench_read", "action": "list_cases"},
    )

    assert response.status_code == 401


def test_dispatch_rejects_wrong_bearer_token() -> None:
    response = _client().post(
        "/v1/tools:dispatch",
        headers={"Authorization": "Bearer wrong-token"},
        json={"tool": "toee_workbench_read", "action": "list_cases"},
    )

    assert response.status_code == 401


def test_dispatch_runs_allowlisted_action_and_returns_governed_json() -> None:
    # Allowlisted copilot read → execute_tool runs the mock handler and its JSON
    # comes back under ok/data (ADR-0141 deterministic dispatch).
    response = _client().post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={"tool": "toee_workbench_read", "action": "list_cases"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"] == {"cases": []}


def test_dispatch_passes_params_through_to_handler() -> None:
    # params reach the handler: get_case echoes the requested case_id.
    response = _client().post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_workbench_read",
            "action": "get_case",
            "params": {"case_id": "case_42"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["case_id"] == "case_42"


def test_dispatch_denies_tool_outside_profile_allowlist() -> None:
    # toee_workbench_admin is supervisor-only (ADR-0038). Under the internal
    # copilot profile it is a governed denial — HTTP 200, ok False, not raised.
    response = _client().post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={"tool": "toee_workbench_admin", "action": "list_accounts"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["class"] == "policy_blocked"


def test_dispatch_unknown_tool_is_governed_not_raised() -> None:
    # Unknown tool is caught by execute_tool's catalog check before the gate, so it
    # is a governed unknown_tool failure (HTTP 200), still never a raised exception.
    response = _client().post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={"tool": "toee_not_a_tool", "action": "list_cases"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["class"] == "unknown_tool"


def test_dispatch_threads_actor_account_id_into_context() -> None:
    # ADR-0141 actor attribution: the BFF-asserted acting account rides the request
    # body and must reach ToolExecutionContext.user_id so governed writes (and the
    # case_view read audit) attribute to the real employee instead of NULL.
    driver = _CapturingDriver()
    response = _client_with_driver(driver).post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_workbench_read",
            "action": "list_cases",
            "actor_account_id": "acct_rep_7",
        },
    )

    assert response.status_code == 200
    assert driver.context is not None
    assert driver.context.user_id == "acct_rep_7"


def test_dispatch_without_actor_runs_with_no_actor() -> None:
    # Absent actor stays fail-open (user_id None), matching the prior behavior for
    # reads that tolerate it; the BFF always supplies one for governed writes.
    driver = _CapturingDriver()
    _client_with_driver(driver).post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={"tool": "toee_workbench_read", "action": "list_cases"},
    )

    assert driver.context is not None
    assert driver.context.user_id is None


def test_dispatch_actor_attributes_the_audit_actor_end_to_end(datastore) -> None:
    # End-to-end (ADR-0141): an HTTP dispatch carrying actor_account_id runs the
    # governed claim through the real datastore and the audit row it writes is
    # attributed to that actor — proving the actor flows request -> context -> audit,
    # not just into the context. Skip-if-no-DB via the shared fixture (ADR-0142).
    from toee_hermes.execute import execute_tool
    from toee_hermes.tool_gate import ToolExecutionContext

    driver, _, _ = datastore
    case_id = execute_tool(
        tool="toee_case",
        action="create_case",
        params={"contact_reason": "x"},
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    ).data["case_id"]

    response = _client_with_driver(driver).post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_case_manage",
            "action": "claim_case",
            "params": {"case_id": case_id},
            "actor_account_id": "acct_actor_e2e",
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True

    entries = execute_tool(
        tool="toee_workbench_read",
        action="get_audit_log",
        params={"case_id": case_id},
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    ).data["entries"]
    claim = next(e for e in entries if e["action"] == "claim_case")
    assert claim["account_id"] == "acct_actor_e2e"


def test_dispatch_governed_write_without_actor_is_denied(datastore) -> None:
    # I1 regression end-to-end (ADR-0141): a governed case write dispatched with NO
    # actor_account_id is a governed denial (HTTP 200, ok False), and it leaves NO
    # mutation and NO NULL-actor audit row behind — the silent wrong-success the
    # cutover must not allow. Reads stay fail-open; only writes require the actor.
    from toee_hermes.execute import execute_tool
    from toee_hermes.tool_gate import ToolExecutionContext

    driver, _, _ = datastore
    case_id = execute_tool(
        tool="toee_case",
        action="create_case",
        params={"contact_reason": "x"},
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    ).data["case_id"]

    response = _client_with_driver(driver).post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_case_manage",
            "action": "claim_case",
            "params": {"case_id": case_id},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["class"] == "policy_blocked"

    case = execute_tool(
        tool="toee_workbench_read",
        action="get_case",
        params={"case_id": case_id},
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    ).data["case"]
    assert case["assignee_account_id"] is None
    assert case["status"] == "open"

    entries = execute_tool(
        tool="toee_workbench_read",
        action="get_audit_log",
        params={"case_id": case_id},
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    ).data["entries"]
    assert [e for e in entries if e["action"] == "claim_case"] == []


def test_dispatch_rejects_malformed_body() -> None:
    # Missing tool/action is a transport/shape problem, not a tool outcome → 400.
    response = _client().post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={"action": "list_cases"},
    )

    assert response.status_code == 400
