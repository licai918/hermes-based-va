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

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from hermes_runtime.agent_turn_app import AGENT_TURN_PATH, add_agent_turn_route

API_TOKEN = "test-copilot-api-token"


@pytest.fixture(autouse=True)
def _keyless_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # The default provider is keyed off OPENROUTER_API_KEY (Fork C1); clear it so the
    # end-to-end default-provider tests below exercise the deterministic keyless stub
    # even on a dev box that exports a real key — CI never makes a network call.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


def _fake_run_turn(*, channel: str, case_id: str, prompt: str | None = None) -> dict:
    return {
        "draft": f"draft for {case_id}",
        "model": "scripted",
        "profile": "internal_copilot",
    }


def _email_run_turn(*, channel: str, case_id: str, prompt: str | None = None) -> dict:
    # Email turns additionally return a subject (Slice 2): the endpoint shapes it
    # into the {channel, subject, draft} envelope.
    return {
        "draft": f"email body for {case_id}",
        "subject": f"Subject for {case_id}",
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
    # Exhaustive key-set: the sms envelope is EXACTLY {channel, draft, provenance}
    # (ADR-0147 Slice 2 review follow-up). Pinned on the Python side, where envelope
    # shape responsibility now lives after the BFF's pass-through change — so a future
    # drift (e.g. spreading the whole `result` into `data`) breaks here, which the
    # frozen-fixture BFF tests cannot catch.
    assert set(body["data"]) == {"channel", "draft", "provenance"}
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


# ADR-0147 Slice 2: the per-channel `data` envelope mirrors the in-process
# toee_copilot_draft tool output byte-for-byte — sms/email key on `channel`, email
# adds `subject`, internal_note keys on `kind` (no channel) — so the BFF body has
# exact store-path parity for all three channels.
def test_agent_turn_email_data_includes_subject() -> None:
    response = _client(_email_run_turn).post(
        AGENT_TURN_PATH,
        headers=_auth(),
        json={"channel": "email", "case_id": "case_e"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    # Exhaustive key-set: the email envelope is EXACTLY {channel, subject, draft,
    # provenance} — `subject` is the one key that distinguishes it from sms.
    assert set(data) == {"channel", "subject", "draft", "provenance"}
    assert data["channel"] == "email"
    assert data["subject"] == "Subject for case_e"
    assert data["draft"] == "email body for case_e"
    assert data["provenance"] == {"model": "scripted", "profile": "internal_copilot"}


def test_agent_turn_internal_note_data_keys_on_kind() -> None:
    response = _client().post(
        AGENT_TURN_PATH,
        headers=_auth(),
        json={"channel": "internal_note", "case_id": "case_n"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    # Note envelope: EXACTLY {kind, draft, provenance} — keys on `kind`, and
    # crucially carries NO `channel` key (the key-set equality pins that absence).
    assert set(data) == {"kind", "draft", "provenance"}
    assert data["kind"] == "internal_note"
    assert "channel" not in data
    assert data["draft"] == "draft for case_n"
    assert data["provenance"]["profile"] == "internal_copilot"


def test_agent_turn_audit_is_a_noop_without_a_datastore_driver() -> None:
    # #47 option (i), mock-first sink: a driver lacking `record_audit` (the
    # MockDriver) — or no driver at all — makes the server-side draft_generated audit
    # a no-op. The draft still returns 200 with no crash, exactly like every other
    # API-path governed write in mock mode (the persisted-row proof is the datastore
    # test test_agent_turn_audit; here we only pin the no-op-doesn't-blow-up contract).
    class _MockLikeDriver:  # stands in for MockDriver: no record_audit method
        kind = "mock"

    app = FastAPI()
    add_agent_turn_route(
        app, api_token=API_TOKEN, run_turn=_fake_run_turn, driver=_MockLikeDriver()
    )
    response = TestClient(app).post(
        AGENT_TURN_PATH,
        headers=_auth(),
        json={"channel": "sms", "case_id": "c1", "actor_account_id": "a"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True


# ADR-0147 Slice 4 (#39): the conversational `chat` turn-mode. Unlike the three
# draft channels, chat returns a `{reply, provenance}` envelope (a conversational
# reply, not a per-channel draft) and records NO draft_generated audit — parity with
# the in-memory handleChat, which writes none (the no-audit invariant is pinned
# server-side in test_agent_turn_audit::test_chat_turn_records_no_audit).
def test_agent_turn_chat_returns_a_reply_envelope() -> None:
    response = _client().post(
        AGENT_TURN_PATH,
        headers=_auth(),
        json={"channel": "chat", "case_id": "case_ar_urgent", "actor_account_id": "acct_rep_7"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    # Exhaustive key-set: chat is EXACTLY {reply, provenance} — it keys on `reply`
    # (not `channel`/`draft`/`kind`/`subject`), so a future drift toward a draft
    # envelope breaks here.
    assert set(body["data"]) == {"reply", "provenance"}
    assert body["data"]["reply"] == "draft for case_ar_urgent"
    assert body["data"]["provenance"] == {"model": "scripted", "profile": "internal_copilot"}


def test_agent_turn_chat_threads_message_as_prompt_to_run_turn() -> None:
    captured: dict = {}

    def run_turn(*, channel: str, case_id: str, prompt: str | None = None) -> dict:
        captured.update(channel=channel, case_id=case_id, prompt=prompt)
        return {"draft": "ok", "model": "scripted", "profile": "internal_copilot"}

    response = _client(run_turn).post(
        AGENT_TURN_PATH,
        headers=_auth(),
        json={"channel": "chat", "case_id": "c1", "prompt": "what's going on?"},
    )
    assert response.status_code == 200
    assert captured == {"channel": "chat", "case_id": "c1", "prompt": "what's going on?"}


def test_agent_turn_chat_end_to_end_default_provider_boots_internal_copilot() -> None:
    # The chat seam end to end with the default scripted/stub provider: boots
    # internal_copilot UNBOUND and returns a non-empty reply + internal_copilot
    # provenance over HTTP, keyless — exactly like the draft end-to-end test.
    app = FastAPI()
    add_agent_turn_route(app, api_token=API_TOKEN)
    response = TestClient(app).post(
        AGENT_TURN_PATH, headers=_auth(), json={"channel": "chat", "case_id": "case_x"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert isinstance(data["reply"], str) and data["reply"].strip()
    assert data["provenance"]["profile"] == "internal_copilot"


def test_agent_turn_end_to_end_email_default_provider_includes_subject() -> None:
    # The email seam end to end with the default scripted/stub provider: boots
    # internal_copilot unbound and returns a {channel:email, subject, draft} envelope
    # — proving the default run_turn supplies a subject (no KeyError) over HTTP.
    app = FastAPI()
    add_agent_turn_route(app, api_token=API_TOKEN)
    response = TestClient(app).post(
        AGENT_TURN_PATH, headers=_auth(), json={"channel": "email", "case_id": "case_x"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["channel"] == "email"
    assert isinstance(data["subject"], str) and data["subject"].strip()
    assert isinstance(data["draft"], str) and data["draft"].strip()
