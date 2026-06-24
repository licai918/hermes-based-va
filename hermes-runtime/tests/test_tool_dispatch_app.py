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


def test_dispatch_rejects_malformed_body() -> None:
    # Missing tool/action is a transport/shape problem, not a tool outcome → 400.
    response = _client().post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={"action": "list_cases"},
    )

    assert response.status_code == 400
