"""P1 runtime-shim smoke (PRD "Hermes runtime shim — smoke test with mock adapters
registered"): boot the REAL upstream Hermes PluginContext, register the toee_hermes
plugin under the external profile, and prove governed dispatch flows registry ->
handler -> execute_tool -> MockDriver (ADR-0139 verification, now landed in-repo).
"""

from __future__ import annotations

import json

from hermes_runtime.boot import boot_profile


def test_external_profile_boots_23_governed_toee_tools() -> None:
    # ADR-0034 external allowlist registers exactly 23 action-tools (ADR-0139).
    # 0.0.3 S15 adds toee_customer_memory.dismiss_proposal: it rides the same
    # shared toolset upsert/clear/get_preferences already use, so it is also
    # registered here even though the external (customer-facing) profile never
    # legitimately calls it -- a call would still be policy_blocked (no
    # attributed actor), same defense-in-depth as every other employee-only
    # write on this toolset. 0.0.3 S21 adds
    # toee_customer_memory.get_my_memory_summary: unlike get_memory_audit (still
    # excluded), this one IS deliberately customer-facing (FR-21), so it is a
    # real +1 to the external model's tool-calling surface, not defense-in-depth.
    booted = boot_profile("customer_service_external")
    toee_tools = [name for name in booted.tool_names if name.startswith("toee_")]
    assert len(toee_tools) == 23


def test_external_profile_dispatch_returns_governed_json() -> None:
    # Dispatch through the real registry must reach our MockDriver and return a
    # JSON object (governed result envelope), never raise (ADR-0020).
    booted = boot_profile("customer_service_external")
    raw = booted.dispatch(
        "toee_identity_lookup__match_phone", {"phone": "+15555550100"}
    )
    assert isinstance(json.loads(raw), dict)
