"""Server-side ``draft_generated`` audit on the agent:turn route (ADR-0147 #47).

Closes the Slice 3 deferral via **option (i)**: the ``agent:turn`` endpoint records
the ``draft_generated`` audit server-side through the *existing* datastore writer
(``PostgresDriver.record_audit`` → ``insert_audit``) — the same path the case-mutation
cutover uses — so the row lands in the Postgres ``workbench_audit_log`` the governed
read (``toee_workbench_read.get_audit_log``) now consults, retiring the BFF's
write-only-in-API-mode audit. These prove the row on success (and that it surfaces
through ``get_audit_log``), the per-channel ``detail``, and its absence on a failed
turn. Skip-if-no-DB via the shared ``datastore`` fixture (ADR-0142).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

from hermes_runtime.agent_turn_app import AGENT_TURN_PATH, add_agent_turn_route

API_TOKEN = "test-copilot-api-token"


def _ctx(user_id: str | None = None) -> ToolExecutionContext:
    return ToolExecutionContext(profile="internal_copilot", user_id=user_id)


def _make_case(driver) -> str:
    created = execute_tool(
        tool="toee_case",
        action="create_case",
        params={"contact_reason": "delivery_issue"},
        context=_ctx(),
        driver=driver,
    )
    assert created.ok
    return created.data["case_id"]


def _draft_audit_entries(driver, case_id: str) -> list[dict]:
    audit = execute_tool(
        tool="toee_workbench_read",
        action="get_audit_log",
        params={"case_id": case_id},
        context=_ctx(),
        driver=driver,
    )
    assert audit.ok
    return [e for e in audit.data["entries"] if e["action"] == "draft_generated"]


def _fake_run_turn(*, channel: str, case_id: str, prompt: str | None = None) -> dict:
    # Email needs a subject in the envelope; harmless for sms/internal_note.
    return {
        "draft": f"draft for {case_id}",
        "subject": f"Subject for {case_id}",
        "model": "scripted",
        "profile": "internal_copilot",
    }


def _client(driver, run_turn=_fake_run_turn) -> TestClient:
    app = FastAPI()
    add_agent_turn_route(app, api_token=API_TOKEN, run_turn=run_turn, driver=driver)
    # raise_server_exceptions=False so a deliberately-failing turn returns a 500
    # response (the failure path) instead of re-raising into the test.
    return TestClient(app, raise_server_exceptions=False)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


def test_successful_draft_records_one_audit_readable_via_get_audit_log(datastore) -> None:
    # Acceptance criteria: a successful agent:turn draft records a draft_generated row
    # (target_type=case, target_id=<case>, action=draft_generated, details.detail=
    # draft_sms, account_id=<actor>, profile=internal_copilot), readable through the
    # SAME governed read the cut-over audit-log view uses.
    driver, _, _ = datastore
    case_id = _make_case(driver)

    resp = _client(driver).post(
        AGENT_TURN_PATH,
        headers=_auth(),
        json={"channel": "sms", "case_id": case_id, "actor_account_id": "acct_rep_7"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    drafts = _draft_audit_entries(driver, case_id)
    assert len(drafts) == 1  # exactly one audit per successful draft (no double-write)
    entry = drafts[0]
    assert entry["target_type"] == "case"
    assert entry["target_id"] == case_id
    assert entry["account_id"] == "acct_rep_7"  # attributed to the actor
    assert entry["profile"] == "internal_copilot"
    assert entry["details"] == {"detail": "draft_sms"}


@pytest.mark.parametrize(
    "channel,detail",
    [
        ("sms", "draft_sms"),
        ("email", "draft_email"),
        ("internal_note", "draft_internal_note"),
    ],
)
def test_draft_generated_detail_is_the_channel_action(datastore, channel, detail) -> None:
    # detail mirrors the BFF draft_generated semantics byte-for-byte: the channel
    # ACTION (draft_sms / draft_email / draft_internal_note), not the bare channel.
    driver, _, _ = datastore
    case_id = _make_case(driver)

    resp = _client(driver).post(
        AGENT_TURN_PATH, headers=_auth(), json={"channel": channel, "case_id": case_id}
    )
    assert resp.status_code == 200

    drafts = _draft_audit_entries(driver, case_id)
    assert [e["details"] for e in drafts] == [{"detail": detail}]


def test_failed_turn_records_no_audit(datastore) -> None:
    # No audit on failure: when the turn raises before producing a draft, the route
    # never reaches the (post-success) audit write, so no draft_generated row lands.
    driver, _, _ = datastore
    case_id = _make_case(driver)

    def boom(*, channel: str, case_id: str, prompt: str | None = None) -> dict:
        raise RuntimeError("turn blew up before producing a draft")

    resp = _client(driver, boom).post(
        AGENT_TURN_PATH, headers=_auth(), json={"channel": "sms", "case_id": case_id}
    )
    assert resp.status_code == 500
    assert _draft_audit_entries(driver, case_id) == []
