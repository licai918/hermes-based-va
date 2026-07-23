"""0.0.4 S15 (FR-23): the ``toee_integrations`` status-page read.

Pure config-presence over the process environment -- no DB, so these call the
handler directly (it ignores ``conn``). Proves: honest ``not_configured`` when a
credential is absent (never a fabricated ``healthy``), green only when the real
credential AND -- for Composio -- a non-``latest`` version pin are present, the
S16-pending fields stay null, and NO secret value ever appears in the output
(NFR-6, the secret-scan spine).
"""

from __future__ import annotations

import json

from hermes_runtime.datastore.handlers.integrations import (
    _get_integrations_status,
    integrations_handlers,
)
from toee_hermes.tool_gate import ToolExecutionContext

_CTX = ToolExecutionContext(profile="supervisor_admin")

# Every integration credential env this read looks at -- cleared before each case
# so a stray real env var in the dev shell can't make an "unconfigured" test pass.
_CRED_ENVS = [
    "COMPOSIO_API_KEY",
    "COMPOSIO_SHOPIFY_CONNECTED_ACCOUNT_ID",
    "COMPOSIO_QBO_CONNECTED_ACCOUNT_ID",
    "COMPOSIO_SQUARE_CONNECTED_ACCOUNT_ID",
    "COMPOSIO_TOOLKIT_VERSION_SHOPIFY",
    "COMPOSIO_TOOLKIT_VERSION_QUICKBOOKS",
    "COMPOSIO_TOOLKIT_VERSION_SQUARE",
    "EASYROUTES_API_TOKEN",
    "EASYROUTES_CLIENT_ID",
    "SIMPLETEXTING_API_TOKEN",
    "OPENROUTER_API_KEY",
    "GADGET_API_KEY",
    "INTEGRATION_DRIVER",
]


def _clear(monkeypatch):
    for name in _CRED_ENVS:
        monkeypatch.delenv(name, raising=False)


def _run():
    return _get_integrations_status(None, {}, _CTX)


def _by_key(result):
    return {row["key"]: row for row in result["integrations"]}


def test_registry_exposes_the_action():
    assert integrations_handlers() == {
        "toee_integrations": {"get_integrations_status": _get_integrations_status}
    }


def test_all_unset_is_not_configured_never_healthy(monkeypatch):
    _clear(monkeypatch)
    result = _run()
    rows = _by_key(result)

    # The six PAC-7 integrations plus the Gadget mapping endpoint (S27, a T4
    # integration too) = seven rows.
    assert set(rows) == {
        "shopify",
        "qbo",
        "square",
        "easyroutes",
        "simpletexting",
        "openrouter",
        "gadget",
    }
    for row in rows.values():
        assert row["configured"] is False
        assert row["status"] == "not_configured"
        # S16/S17-pending: honest nulls, never a fabricated timestamp/health.
        assert row["last_successful_call"] is None
        assert row["last_probe"] is None
    assert result["active_driver"] == "mock"


def test_composio_needs_key_account_and_pin(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("INTEGRATION_DRIVER", "composio")
    monkeypatch.setenv("COMPOSIO_API_KEY", "ak_secret")
    monkeypatch.setenv("COMPOSIO_SHOPIFY_CONNECTED_ACCOUNT_ID", "acc_secret")
    # Connected but no pin -> still not configured, and the reason is the missing pin.
    rows = _by_key(_run())
    assert rows["shopify"]["configured"] is False
    assert "COMPOSIO_TOOLKIT_VERSION_SHOPIFY" in rows["shopify"]["detail"]
    assert rows["shopify"]["pinned_version"] is None
    # QBO has neither account nor pin -> configured False.
    assert rows["qbo"]["configured"] is False

    monkeypatch.setenv("COMPOSIO_TOOLKIT_VERSION_SHOPIFY", "20250101")
    rows = _by_key(_run())
    assert rows["shopify"]["configured"] is True
    assert rows["shopify"]["status"] == "configured"
    assert rows["shopify"]["pinned_version"] == "20250101"


def test_latest_pin_is_not_a_real_pin(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("COMPOSIO_API_KEY", "ak")
    monkeypatch.setenv("COMPOSIO_SQUARE_CONNECTED_ACCOUNT_ID", "acc")
    monkeypatch.setenv("COMPOSIO_TOOLKIT_VERSION_SQUARE", "latest")
    rows = _by_key(_run())
    assert rows["square"]["configured"] is False
    assert rows["square"]["pinned_version"] is None


def test_presence_flips_each_env_backed_integration(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("EASYROUTES_API_TOKEN", "t")
    monkeypatch.setenv("EASYROUTES_CLIENT_ID", "c")
    monkeypatch.setenv("SIMPLETEXTING_API_TOKEN", "s")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    monkeypatch.setenv("GADGET_API_KEY", "g")
    rows = _by_key(_run())
    for key in ("easyroutes", "simpletexting", "openrouter", "gadget"):
        assert rows[key]["configured"] is True, key
        assert rows[key]["status"] == "configured"


def test_no_secret_value_ever_leaves(monkeypatch):
    _clear(monkeypatch)
    secret = "TOP_SECRET_TOKEN_VALUE_12345"
    # Only the credential/account envs carry the secret. The version-pin envs are
    # deliberately NOT secrets (a Composio toolkit version is surfaced), so they get
    # a real version string -- the assertion is that no credential VALUE leaks.
    for name in _CRED_ENVS:
        if name == "INTEGRATION_DRIVER" or "VERSION" in name:
            continue
        monkeypatch.setenv(name, secret)
    monkeypatch.setenv("COMPOSIO_TOOLKIT_VERSION_SHOPIFY", "20250101")
    monkeypatch.setenv("COMPOSIO_TOOLKIT_VERSION_QUICKBOOKS", "20250101")
    monkeypatch.setenv("COMPOSIO_TOOLKIT_VERSION_SQUARE", "20250101")
    blob = json.dumps(_run())
    assert secret not in blob
