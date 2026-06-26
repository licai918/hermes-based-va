"""Slice 34 / #37: per-profile tool-dispatch server composition root.

``build_tool_dispatch_app`` assembles the ADR-0141 dispatch app from the
environment, fail-closed like ``gateway_composition.build_gateway_app``: the
profile selector ``TOEE_HERMES_PROFILE`` and the per-process bearer
``DISPATCH_API_TOKEN``. Mock-first (``TOOL_BACKEND`` unset), so these need no
Postgres — only that the env-driven assembly and the governed contract hold.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from toee_hermes.plugin.profiles import PROFILE_ENV_VAR

from hermes_runtime.tool_dispatch_composition import (
    DISPATCH_API_TOKEN_ENV,
    build_tool_dispatch_app,
)


def _configure(monkeypatch, *, profile="internal_copilot", token="dev-token") -> None:
    # Force the mock backend so the app needs no database.
    monkeypatch.delenv("TOOL_BACKEND", raising=False)
    if profile is None:
        monkeypatch.delenv(PROFILE_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(PROFILE_ENV_VAR, profile)
    if token is None:
        monkeypatch.delenv(DISPATCH_API_TOKEN_ENV, raising=False)
    else:
        monkeypatch.setenv(DISPATCH_API_TOKEN_ENV, token)


def test_missing_profile_fails_closed(monkeypatch) -> None:
    _configure(monkeypatch, profile=None)
    with pytest.raises(ValueError):
        build_tool_dispatch_app()


def test_unknown_profile_fails_closed(monkeypatch) -> None:
    _configure(monkeypatch, profile="not_a_profile")
    with pytest.raises(ValueError):
        build_tool_dispatch_app()


def test_missing_token_fails_closed(monkeypatch) -> None:
    _configure(monkeypatch, token=None)
    with pytest.raises(ValueError):
        build_tool_dispatch_app()


def test_built_app_serves_healthz(monkeypatch) -> None:
    _configure(monkeypatch)
    client = TestClient(build_tool_dispatch_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_built_app_enforces_bearer_token(monkeypatch) -> None:
    _configure(monkeypatch)
    client = TestClient(build_tool_dispatch_app())
    response = client.post(
        "/v1/tools:dispatch",
        json={"tool": "toee_workbench_read", "action": "list_cases"},
    )
    assert response.status_code == 401


def test_built_app_runs_allowlisted_tool_for_its_profile(monkeypatch) -> None:
    _configure(monkeypatch, profile="internal_copilot")
    client = TestClient(build_tool_dispatch_app())
    response = client.post(
        "/v1/tools:dispatch",
        headers={"Authorization": "Bearer dev-token"},
        json={"tool": "toee_workbench_read", "action": "list_cases"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_built_app_denies_tool_outside_its_profile(monkeypatch) -> None:
    # toee_workbench_admin is supervisor-only (ADR-0038); under the copilot
    # profile the per-profile gate returns a governed policy_blocked, not a raise.
    _configure(monkeypatch, profile="internal_copilot")
    client = TestClient(build_tool_dispatch_app())
    response = client.post(
        "/v1/tools:dispatch",
        headers={"Authorization": "Bearer dev-token"},
        json={"tool": "toee_workbench_admin", "action": "list_accounts"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["class"] == "policy_blocked"


def test_built_app_serves_agent_turn_route(monkeypatch) -> None:
    # ADR-0147 Fork A1: the same per-profile server serves BOTH tools:dispatch and
    # agent:turn behind one bearer. Bearer is enforced (401), and an authed turn
    # boots internal_copilot UNBOUND and returns a scripted draft + provenance.
    _configure(monkeypatch, profile="internal_copilot")
    client = TestClient(build_tool_dispatch_app())

    assert (
        client.post("/v1/agent:turn", json={"channel": "sms", "case_id": "c1"}).status_code
        == 401
    )

    response = client.post(
        "/v1/agent:turn",
        headers={"Authorization": "Bearer dev-token"},
        json={"channel": "sms", "case_id": "case_x"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["provenance"]["profile"] == "internal_copilot"


def test_agent_turn_route_is_internal_copilot_only(monkeypatch) -> None:
    # ADR-0147 M3: the agent:turn LLM draft seam is mounted ONLY on the copilot
    # (INTERNAL) server. A SUPERVISOR/EXTERNAL dispatch server still serves the
    # deterministic surface (healthz/tools:dispatch) but NOT agent:turn — so the LLM
    # route is absent (404) on a server that should never draft, even with the right
    # bearer. Guards against the route silently widening to every per-profile server.
    for profile in ("supervisor_admin", "customer_service_external"):
        _configure(monkeypatch, profile=profile)
        client = TestClient(build_tool_dispatch_app())
        assert client.get("/healthz").status_code == 200  # deterministic surface stays
        resp = client.post(
            "/v1/agent:turn",
            headers={"Authorization": "Bearer dev-token"},
            json={"channel": "sms", "case_id": "c1"},
        )
        assert resp.status_code == 404, f"agent:turn must not be mounted on {profile}"
