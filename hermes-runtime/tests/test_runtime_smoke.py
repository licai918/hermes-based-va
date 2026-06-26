"""P1 runtime-shim smoke (PRD "Hermes runtime shim — smoke test with mock adapters
registered"): boot the REAL upstream Hermes PluginContext, register the toee_hermes
plugin under the external profile, and prove governed dispatch flows registry ->
handler -> execute_tool -> MockDriver (ADR-0139 verification, now landed in-repo).
"""

from __future__ import annotations

import json

from hermes_runtime.boot import boot_profile


def test_external_profile_boots_21_governed_toee_tools() -> None:
    # ADR-0034 external allowlist registers exactly 21 action-tools (ADR-0139).
    booted = boot_profile("customer_service_external")
    toee_tools = [name for name in booted.tool_names if name.startswith("toee_")]
    assert len(toee_tools) == 21


def test_external_profile_dispatch_returns_governed_json() -> None:
    # Dispatch through the real registry must reach our MockDriver and return a
    # JSON object (governed result envelope), never raise (ADR-0020).
    booted = boot_profile("customer_service_external")
    raw = booted.dispatch(
        "toee_identity_lookup__match_phone", {"phone": "+15555550100"}
    )
    assert isinstance(json.loads(raw), dict)
