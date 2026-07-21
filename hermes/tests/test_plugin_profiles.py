"""P5 profile allowlist + pre_llm_call injection tests.

Profile allowlists (ADR-0034 external, ADR-0035 internal copilot, ADR-0038
supervisor admin) are transcribed here as the test's source of truth; the plugin
must match them exactly. ``pre_llm_call`` injection follows ADR-0140 / ADR-0113:
append the Session Identity Snapshot + a compact Customer Memory block to the
user turn, never the system prompt, and never break the turn on provider error.
"""

from __future__ import annotations

import pytest

from toee_hermes.plugin.hooks import make_pre_llm_call_hook, render_injection
from toee_hermes.plugin.profiles import (
    DEFAULT_PROFILE,
    PROFILE_TOOL_ALLOWLIST,
    PROFILES,
    allowlisted_tools,
    resolve_profile,
)
from toee_hermes.tool_catalog import TOOL_CATALOG

ADR_0034_EXTERNAL = {
    "toee_knowledge_search",
    "toee_shopify_read",
    "toee_qbo_read",
    "toee_easyroutes_read",
    "toee_square_payment_link",
    "toee_textline_reply",
    "toee_case",
    "toee_identity_lookup",
    "toee_customer_memory",
}
ADR_0035_INTERNAL = {
    "toee_knowledge_search",
    "toee_shopify_read",
    "toee_qbo_read",
    "toee_easyroutes_read",
    "toee_identity_lookup",
    "toee_case_manage",
    "toee_copilot_draft",
    "toee_workbench_read",
    "toee_customer_memory",
    # 0.0.3 S22 (FR-23): L6 Agent-experience proposals -- internal_copilot only.
    "toee_agent_experience",
}
ADR_0038_SUPERVISOR = {
    "toee_knowledge_ops",
    "toee_eval_review",
    "toee_workbench_admin",
    "toee_workbench_read",
    "toee_knowledge_search",
}


# --- profiles --------------------------------------------------------------


def test_profiles_are_the_three_adr_profiles() -> None:
    assert set(PROFILES) == {
        "customer_service_external",
        "internal_copilot",
        "supervisor_admin",
    }
    assert DEFAULT_PROFILE == "customer_service_external"


def test_allowlists_match_adrs() -> None:
    assert set(PROFILE_TOOL_ALLOWLIST["customer_service_external"]) == ADR_0034_EXTERNAL
    assert set(PROFILE_TOOL_ALLOWLIST["internal_copilot"]) == ADR_0035_INTERNAL
    assert set(PROFILE_TOOL_ALLOWLIST["supervisor_admin"]) == ADR_0038_SUPERVISOR


def test_every_allowlisted_tool_exists_in_catalog() -> None:
    for profile in PROFILES:
        for tool in allowlisted_tools(profile):
            assert tool in TOOL_CATALOG


def test_profiles_union_covers_all_catalog_tools() -> None:
    union: set[str] = set()
    for profile in PROFILES:
        union |= set(allowlisted_tools(profile))
    assert union == set(TOOL_CATALOG)


def test_allowlisted_tools_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError):
        allowlisted_tools("not_a_profile")


def test_resolve_profile_prefers_ctx_then_env_then_default(monkeypatch) -> None:
    class Ctx:
        profile = "internal_copilot"

    monkeypatch.delenv("TOEE_HERMES_PROFILE", raising=False)
    assert resolve_profile(Ctx()) == "internal_copilot"
    monkeypatch.setenv("TOEE_HERMES_PROFILE", "supervisor_admin")
    assert resolve_profile(None) == "supervisor_admin"
    monkeypatch.delenv("TOEE_HERMES_PROFILE", raising=False)
    assert resolve_profile(None) == DEFAULT_PROFILE


def test_resolve_profile_rejects_unknown(monkeypatch) -> None:
    monkeypatch.setenv("TOEE_HERMES_PROFILE", "nope")
    with pytest.raises(ValueError):
        resolve_profile(None)


# --- pre_llm_call injection (ADR-0140, ADR-0113) ---------------------------


def test_render_injection_returns_none_when_empty() -> None:
    assert render_injection(None, None) is None
    assert render_injection({}, []) is None


def test_pre_llm_call_injects_identity_and_memory() -> None:
    hook = make_pre_llm_call_hook(
        snapshot_provider=lambda sid: {
            "shopify_customer_id": "cust_1",
            "verified": True,
        },
        memory_provider=lambda sid: [{"slot": "preferred_name", "value": "Sam"}],
    )
    out = hook(
        session_id="s1",
        user_message="hi",
        conversation_history=[],
        is_first_turn=True,
        model="m",
        platform="textline",
    )
    assert out is not None
    assert "context" in out
    assert "cust_1" in out["context"]
    assert "preferred_name" in out["context"]


def test_memory_block_is_framed_as_untrusted_data_not_instructions() -> None:
    # FR-6/RK-2: a stored preference is customer-authored free text re-injected every
    # turn — a persistent prompt-injection surface. The block must be wrapped in an
    # explicit untrusted-data delimiter and framed as preferences to honor, never as
    # instructions to obey, while the slot value itself stays intact and unmodified.
    memory = [{"slot": "contact_time_preference", "value": "after 5pm"}]
    out = render_injection(None, memory)

    assert out is not None
    assert "<untrusted_customer_memory>" in out
    assert "</untrusted_customer_memory>" in out
    assert "not instructions to obey" in out
    assert "- contact_time_preference: after 5pm" in out

    # Genuine wrapping, not just incidental substrings anywhere in the string.
    open_tag = out.index("<untrusted_customer_memory>")
    header = out.index("Customer Memory (preferences):")
    slot_line = out.index("- contact_time_preference: after 5pm")
    close_tag = out.index("</untrusted_customer_memory>")
    assert open_tag < header < slot_line < close_tag


def test_pre_llm_call_returns_none_when_nothing_to_inject() -> None:
    hook = make_pre_llm_call_hook()
    out = hook(
        session_id="s1",
        user_message="hi",
        conversation_history=[],
        is_first_turn=True,
        model="m",
        platform="textline",
    )
    assert out is None


def test_pre_llm_call_swallows_provider_errors() -> None:
    def boom(_sid: str):
        raise RuntimeError("provider down")

    hook = make_pre_llm_call_hook(snapshot_provider=boom, memory_provider=boom)
    out = hook(session_id="s1", user_message="hi")
    assert out is None
