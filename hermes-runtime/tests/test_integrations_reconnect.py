"""0.0.4 S17 (FR-25): the two in-app reconnect actions on ``toee_integrations``.

Two shapes: Composio OAuth (``initiate_reconnect`` -> a governed re-auth link) and
on-demand re-probe (``reprobe_now``, the completion step for both shapes). Both are
GOVERNED WRITES: admin-attributed and audited. Proven here:

- attribution is fail-closed (no actor -> denied, no side effect);
- only Composio-managed connections have an OAuth reconnect (a static-token key is
  rejected -- it reconnects via guided env rotation + re-probe);
- a fail-closed Composio link generation writes NO audit row (never a false success);
- a successful link and a re-probe each write exactly one attributed audit row;
- a re-probe records the SAME honest probe state the scheduled job would (owner-blocked
  -> not_configured, never a fabricated ok), plus its audit row.
"""

from __future__ import annotations

import pytest
from toee_hermes.errors import ToolDriverError
from toee_hermes.tool_gate import ToolExecutionContext

from hermes_runtime.datastore.handlers import integrations as H

_ADMIN = ToolExecutionContext(profile="supervisor_admin", user_id="admin_1")
_NO_ACTOR = ToolExecutionContext(profile="supervisor_admin")

_CRED_ENVS = [
    "COMPOSIO_API_KEY",
    "COMPOSIO_SHOPIFY_CONNECTED_ACCOUNT_ID",
    "EASYROUTES_API_TOKEN",
    "EASYROUTES_CLIENT_ID",
    "SIMPLETEXTING_API_TOKEN",
    "OPENROUTER_API_KEY",
    "GADGET_API_KEY",
]


def _clear(monkeypatch):
    for name in _CRED_ENVS:
        monkeypatch.delenv(name, raising=False)


def _audit_rows(conn, action):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT account_id, target_type, target_id, details "
            "FROM workbench_audit_log WHERE action = %s ORDER BY created_at",
            (action,),
        )
        return cur.fetchall()


# --- initiate_reconnect (Composio OAuth) -------------------------------------


def test_reconnect_requires_an_attributed_admin(datastore):
    _driver, conn, _schema = datastore
    with pytest.raises(ToolDriverError) as err:
        H._initiate_reconnect(
            conn,
            {"integration_key": "shopify", "callback_url": "https://wb/cb"},
            _NO_ACTOR,
        )
    assert err.value.error_class == "policy_blocked"
    assert _audit_rows(conn, "integration_reconnect_initiated") == []


def test_reconnect_rejects_a_static_token_integration(datastore):
    _driver, conn, _schema = datastore
    # EasyRoutes has no OAuth -- it reconnects via env rotation + re-probe.
    with pytest.raises(ToolDriverError):
        H._initiate_reconnect(
            conn,
            {"integration_key": "easyroutes", "callback_url": "https://wb/cb"},
            _ADMIN,
        )
    assert _audit_rows(conn, "integration_reconnect_initiated") == []


def test_reconnect_requires_a_callback_url(datastore):
    _driver, conn, _schema = datastore
    with pytest.raises(ToolDriverError):
        H._initiate_reconnect(conn, {"integration_key": "shopify"}, _ADMIN)


def test_reconnect_fail_closed_writes_no_audit(datastore, monkeypatch):
    _driver, conn, _schema = datastore

    def _boom(_key, *, callback_url):  # noqa: ARG001 - signature match
        raise ToolDriverError("composio_api_error", "owner-blocked / wrong guess")

    monkeypatch.setattr(H, "initiate_composio_reconnect", _boom)
    with pytest.raises(ToolDriverError):
        H._initiate_reconnect(
            conn,
            {"integration_key": "qbo", "callback_url": "https://wb/cb"},
            _ADMIN,
        )
    # No fabricated success: nothing audited when the link could not be generated.
    assert _audit_rows(conn, "integration_reconnect_initiated") == []


def test_reconnect_success_returns_link_and_audits_the_admin(datastore, monkeypatch):
    _driver, conn, _schema = datastore
    captured = {}

    def _link(key, *, callback_url):
        captured["key"] = key
        captured["callback_url"] = callback_url
        return "https://provider.example/oauth?x=1"

    monkeypatch.setattr(H, "initiate_composio_reconnect", _link)
    out = H._initiate_reconnect(
        conn,
        {"integration_key": "square", "callback_url": "https://wb/cb?state=abc"},
        _ADMIN,
    )
    assert out == {
        "integration_key": "square",
        "redirect_url": "https://provider.example/oauth?x=1",
    }
    # The workbench-built callback_url is passed straight through to the SDK layer.
    assert captured == {"key": "square", "callback_url": "https://wb/cb?state=abc"}

    rows = _audit_rows(conn, "integration_reconnect_initiated")
    assert len(rows) == 1
    account_id, target_type, target_id, details = rows[0]
    assert account_id == "admin_1"
    assert (target_type, target_id) == ("integration", "square")
    assert details == {"toolkit": "square"}


# --- reprobe_now (both shapes' completion) -----------------------------------


def test_reprobe_requires_an_attributed_admin(datastore, monkeypatch):
    _driver, conn, _schema = datastore
    _clear(monkeypatch)
    with pytest.raises(ToolDriverError) as err:
        H._reprobe_now(conn, {"integration_key": "easyroutes"}, _NO_ACTOR)
    assert err.value.error_class == "policy_blocked"


def test_reprobe_rejects_an_unknown_integration(datastore):
    _driver, conn, _schema = datastore
    with pytest.raises(ToolDriverError):
        H._reprobe_now(conn, {"integration_key": "nope"}, _ADMIN)


def test_reprobe_records_the_honest_state_and_audits(datastore, monkeypatch):
    _driver, conn, _schema = datastore
    _clear(monkeypatch)  # owner-blocked -> the probe is SKIPPED, records not_configured

    out = H._reprobe_now(conn, {"integration_key": "openrouter"}, _ADMIN)
    assert out["integration_key"] == "openrouter"
    assert out["status"] == "not_configured"  # never a fabricated ok

    # The fresh probe row is what the page now reads as last_probe.
    row = H._get_integrations_status(conn, {}, _ADMIN)["integrations"]
    last = {r["key"]: r["last_probe"] for r in row}["openrouter"]
    assert last is not None and last["status"] == "not_configured"

    rows = _audit_rows(conn, "integration_reprobed")
    assert len(rows) == 1
    account_id, target_type, target_id, details = rows[0]
    assert account_id == "admin_1"
    assert (target_type, target_id) == ("integration", "openrouter")
    assert details == {"status": "not_configured"}
