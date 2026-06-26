"""``POST /v1/agent:turn`` — the per-profile agent-turn route (ADR-0147 Slice 1).

A second, distinct route beside ``tools:dispatch`` on the same per-profile server
(Fork A1): same bearer auth (constant-time, fail-closed 401) and same
``actor_account_id`` body convention, but it runs a *genuine* unbound
``internal_copilot`` agent turn (Fork B1 synchronous) and returns the draft —
``{ ok, data: { channel, draft, provenance } }``. Auth/shape problems are 4xx,
matching ``tool_dispatch_app``; a governed failure would ride a 200 body.

The model boundary is injected (``run_turn``) so these route tests stay
deterministic; the real scripted seam is proven in ``test_copilot_turn``.
"""

from __future__ import annotations

from fastapi import FastAPI
from starlette.testclient import TestClient

from hermes_runtime.agent_turn_app import AGENT_TURN_PATH, add_agent_turn_route

API_TOKEN = "test-copilot-api-token"


def _fake_run_turn(*, channel: str, case_id: str, prompt: str | None = None) -> dict:
    return {
        "draft": f"draft for {case_id}",
        "model": "scripted",
        "profile": "internal_copilot",
    }


def _client(run_turn=_fake_run_turn) -> TestClient:
    app = FastAPI()
    add_agent_turn_route(app, api_token=API_TOKEN, run_turn=run_turn)
    return TestClient(app)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


def test_agent_turn_requires_bearer_token() -> None:
    # No Authorization header → 401; the turn never runs (fail-closed, ADR-0106).
    response = _client().post(AGENT_TURN_PATH, json={"channel": "sms", "case_id": "c1"})
    assert response.status_code == 401


def test_agent_turn_rejects_wrong_bearer_token() -> None:
    response = _client().post(
        AGENT_TURN_PATH,
        headers={"Authorization": "Bearer wrong-token"},
        json={"channel": "sms", "case_id": "c1"},
    )
    assert response.status_code == 401


def test_agent_turn_rejects_body_missing_channel() -> None:
    # Shape problem (not a turn outcome) → 400, parity with tool_dispatch_app.
    response = _client().post(AGENT_TURN_PATH, headers=_auth(), json={"case_id": "c1"})
    assert response.status_code == 400


def test_agent_turn_rejects_unknown_channel() -> None:
    response = _client().post(
        AGENT_TURN_PATH, headers=_auth(), json={"channel": "carrier_pigeon", "case_id": "c1"}
    )
    assert response.status_code == 400


def test_agent_turn_rejects_body_missing_case_id() -> None:
    response = _client().post(AGENT_TURN_PATH, headers=_auth(), json={"channel": "sms"})
    assert response.status_code == 400


def test_agent_turn_returns_scripted_draft_and_provenance() -> None:
    response = _client().post(
        AGENT_TURN_PATH,
        headers=_auth(),
        json={"channel": "sms", "case_id": "case_ar_urgent", "actor_account_id": "acct_rep_7"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["channel"] == "sms"
    assert body["data"]["draft"] == "draft for case_ar_urgent"
    # Provenance carries the model boundary + the (structurally no-send) profile.
    assert body["data"]["provenance"] == {"model": "scripted", "profile": "internal_copilot"}


def test_agent_turn_threads_channel_case_and_prompt_to_run_turn() -> None:
    captured: dict = {}

    def run_turn(*, channel: str, case_id: str, prompt: str | None = None) -> dict:
        captured.update(channel=channel, case_id=case_id, prompt=prompt)
        return {"draft": "d", "model": "scripted", "profile": "internal_copilot"}

    response = _client(run_turn).post(
        AGENT_TURN_PATH,
        headers=_auth(),
        json={"channel": "sms", "case_id": "c1", "prompt": "be kind"},
    )
    assert response.status_code == 200
    assert captured == {"channel": "sms", "case_id": "c1", "prompt": "be kind"}


def test_agent_turn_end_to_end_default_provider_boots_internal_copilot() -> None:
    # The true tracer: no injected run_turn → make_copilot_run_turn boots
    # internal_copilot UNBOUND and runs a real AIAgent loop against a keyless stub,
    # returning a non-empty draft + internal_copilot provenance over HTTP. Proves
    # the whole seam end to end with no model (ADR-0147 Verification).
    app = FastAPI()
    add_agent_turn_route(app, api_token=API_TOKEN)  # default scripted/stub provider
    response = TestClient(app).post(
        AGENT_TURN_PATH, headers=_auth(), json={"channel": "sms", "case_id": "case_x"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert isinstance(body["data"]["draft"], str) and body["data"]["draft"].strip()
    assert body["data"]["provenance"]["profile"] == "internal_copilot"
