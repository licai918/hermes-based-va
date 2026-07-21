"""P5 plugin wiring tests (ADR-0139): register(), tool schemas, tool handlers.

These exercise the ``toee_hermes`` Hermes plugin glue against the real plugin
contract (``register(ctx)`` + ``ctx.register_tool`` + ``ctx.register_hook``).
``RecordingCtx`` is a faithful stand-in for the Hermes registration context; the
handlers run the real governed dispatch (:func:`execute_tool`) over the real
:class:`MockDriver`, never a fabricated stub.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from toee_hermes.drivers.mock import MockDriver, create_all_mock_handlers
from toee_hermes.plugin import _AGENT_EXCLUDED_ACTIONS, register, register_turn
from toee_hermes.plugin.profiles import DEFAULT_PROFILE, PROFILE_TOOL_ALLOWLIST
from toee_hermes.plugin.schemas import build_tool_schema, build_tool_schemas, hermes_tool_name
from toee_hermes.plugin.tools import make_tool_handler
from toee_hermes.tool_catalog import TOOL_CATALOG
from toee_hermes.tool_gate import GateDecision, ToolExecutionContext


class RecordingCtx:
    """Minimal stand-in for the Hermes plugin registration context (ADR-0139)."""

    def __init__(self, profile: str | None = None) -> None:
        self.profile = profile
        self.tools: list[dict[str, Any]] = []
        self.hooks: list[tuple[str, Any]] = []

    def register_tool(self, *, name: str, toolset: str, schema: dict, handler: Any) -> None:
        self.tools.append(
            {"name": name, "toolset": toolset, "schema": schema, "handler": handler}
        )

    def register_hook(self, event: str, callback: Any) -> None:
        self.hooks.append((event, callback))

    def registered_toolsets(self) -> set[str]:
        return {t["toolset"] for t in self.tools}

    def registered_names(self) -> list[str]:
        return [t["name"] for t in self.tools]

    def hook_events(self) -> list[str]:
        return [event for event, _ in self.hooks]


def _expected_action_count() -> int:
    return sum(len(actions) for actions in TOOL_CATALOG.values())


def _driver() -> MockDriver:
    return MockDriver(create_all_mock_handlers())


def _external_context_provider(_kwargs: dict[str, Any]) -> ToolExecutionContext:
    return ToolExecutionContext(profile=DEFAULT_PROFILE)


# --- schemas ---------------------------------------------------------------


def test_hermes_tool_name_joins_tool_and_action() -> None:
    assert hermes_tool_name("toee_case", "create_case") == "toee_case__create_case"


def test_build_tool_schemas_covers_every_catalog_action() -> None:
    schemas = build_tool_schemas()
    assert len(schemas) == _expected_action_count()
    for entry in schemas:
        schema = entry["schema"]
        assert schema["name"] == hermes_tool_name(entry["tool"], entry["action"])
        assert entry["toolset"] == entry["tool"]
        assert schema["description"]
        assert schema["parameters"]["type"] == "object"
    names = [entry["schema"]["name"] for entry in schemas]
    assert len(names) == len(set(names))


def test_build_tool_schema_layers_known_param_schemas_for_knowledge_search() -> None:
    # The bug this pins down: every tool advertised an open `{}` object, so the
    # model had to guess param names from persona prose -- non-deterministic
    # per call (S10 diagnosis). Layered schemas fix the two knowledge actions.
    public_site = build_tool_schema("toee_knowledge_search", "search_public_site")["parameters"]
    assert public_site["properties"] == {
        "query": {
            "type": "string",
            "description": "The customer's question or topic to search the public knowledge corpus for.",
        }
    }
    assert public_site["required"] == ["query"]
    assert public_site["additionalProperties"] is True

    policy = build_tool_schema("toee_knowledge_search", "search_operational_policy")["parameters"]
    assert set(policy["properties"]) == {"query", "slot"}
    assert "required" not in policy  # mock accepts either; neither is mandatory
    assert policy["additionalProperties"] is True


def test_build_tool_schema_falls_back_to_open_object_for_unlayered_actions() -> None:
    # get_order stays an open object -- filling the rest of the catalog
    # (the get_order {order_id vs order_number} family) is tracked debt, not
    # this fix's scope.
    schema = build_tool_schema("toee_shopify_read", "get_order")["parameters"]
    assert schema == {"type": "object", "properties": {}, "additionalProperties": True}


# --- handlers --------------------------------------------------------------


def test_handler_returns_json_string_on_success() -> None:
    handler = make_tool_handler(
        tool="toee_workbench_admin",
        action="list_accounts",
        driver=_driver(),
        context_provider=_external_context_provider,
    )
    out = handler({})
    assert isinstance(out, str)
    assert json.loads(out) == {"accounts": []}


def test_handler_returns_governed_error_json_when_gate_denies() -> None:
    def deny_gate(request: Any, context: Any) -> GateDecision:
        return GateDecision(
            allow=False, error_class="policy_blocked", message="blocked by policy"
        )

    handler = make_tool_handler(
        tool="toee_workbench_admin",
        action="list_accounts",
        driver=_driver(),
        context_provider=_external_context_provider,
        gate=deny_gate,
    )
    payload = json.loads(handler({}))
    assert payload["error"] == "blocked by policy"
    assert payload["error_class"] == "policy_blocked"


def test_handler_never_raises_and_accepts_extra_kwargs() -> None:
    handler = make_tool_handler(
        tool="toee_workbench_admin",
        action="list_accounts",
        driver=_driver(),
        context_provider=_external_context_provider,
    )
    out = handler({"unused": 1}, task_id="t1", session_id="s1")
    assert json.loads(out) == {"accounts": []}


def test_handler_tolerates_missing_args() -> None:
    handler = make_tool_handler(
        tool="toee_workbench_admin",
        action="list_accounts",
        driver=_driver(),
        context_provider=_external_context_provider,
    )
    out = handler()
    assert json.loads(out) == {"accounts": []}


# --- register --------------------------------------------------------------


def test_register_external_profile_registers_only_allowlist() -> None:
    ctx = RecordingCtx(profile="customer_service_external")
    register(ctx)
    assert ctx.registered_toolsets() == set(
        PROFILE_TOOL_ALLOWLIST["customer_service_external"]
    )
    allow = PROFILE_TOOL_ALLOWLIST["customer_service_external"]
    excluded_in_allow = sum(1 for tool, _ in _AGENT_EXCLUDED_ACTIONS if tool in allow)
    expected = sum(len(TOOL_CATALOG[tool]) for tool in allow) - excluded_in_allow
    assert len(ctx.tools) == expected
    assert ctx.hook_events() == ["pre_llm_call"]


# --- 0.0.3 S05: link_identity is never LLM-callable (governance) ------------


def test_link_identity_is_never_registered_as_an_llm_tool_for_any_profile() -> None:
    # toee_identity_lookup is allowlisted for BOTH external and internal_copilot
    # (for match_phone/match_email_sender); link_identity must stay off the
    # model's tool-calling surface on every profile that would otherwise expose
    # it, since it's a governed Identity Graph WRITE meant only for the
    # simulator's gated tools:dispatch HTTP path.
    for profile in ("customer_service_external", "internal_copilot"):
        ctx = RecordingCtx(profile=profile)
        register(ctx)
        assert "toee_identity_lookup__link_identity" not in ctx.registered_names()


def test_link_identity_stays_excluded_on_register_turn_too() -> None:
    # register_turn is the live async Textline turn's entry point -- the actual
    # production path a prompt-injected customer message would try to exploit.
    ctx = RecordingCtx(profile="customer_service_external")
    register_turn(ctx, conversation_id="conv_1")
    assert "toee_identity_lookup__link_identity" not in ctx.registered_names()


# --- 0.0.3 S20: get_memory_audit is never LLM-callable (governance) --------


def test_get_memory_audit_is_never_registered_as_an_llm_tool_for_any_profile() -> None:
    # toee_customer_memory is allowlisted for BOTH external and internal_copilot;
    # get_memory_audit must stay off the model's tool-calling surface on every
    # profile that would otherwise expose it, since it's an admin-only read
    # meant only for the Memory Audit Console's gated HTTP path (FR-20).
    for profile in ("customer_service_external", "internal_copilot"):
        ctx = RecordingCtx(profile=profile)
        register(ctx)
        assert "toee_customer_memory__get_memory_audit" not in ctx.registered_names()


# --- 0.0.3 S22: list_agent_experience is never LLM-callable (governance) ---


def test_list_agent_experience_is_never_registered_as_an_llm_tool() -> None:
    # toee_agent_experience is allowlisted for internal_copilot only;
    # list_agent_experience must stay off the model's tool-calling surface --
    # it's an admin-only read meant only for the admin BFF's gated dispatch
    # (FR-23, the get_memory_audit precedent).
    ctx = RecordingCtx(profile="internal_copilot")
    register(ctx)
    assert "toee_agent_experience__list_agent_experience" not in ctx.registered_names()


def test_propose_experience_is_registered_as_an_llm_tool_for_internal_copilot() -> None:
    # Contrast with list_agent_experience above: propose_experience IS the
    # governed write the S23 review fork calls, so it must reach
    # internal_copilot's tool-calling surface, not be excluded.
    ctx = RecordingCtx(profile="internal_copilot")
    register(ctx)
    assert "toee_agent_experience__propose_experience" in ctx.registered_names()


def test_agent_experience_is_not_registered_for_external_profile() -> None:
    # ADR-0034/35: toee_agent_experience is internal_copilot only.
    ctx = RecordingCtx(profile="customer_service_external")
    register(ctx)
    assert "toee_agent_experience" not in ctx.registered_toolsets()


# --- 0.0.3 S21: get_my_memory_summary IS LLM-callable on EXTERNAL (FR-21) ---


def test_get_my_memory_summary_is_registered_as_an_llm_tool_for_external_profile() -> None:
    # Contrast with get_memory_audit above: unlike that admin-only read,
    # get_my_memory_summary is deliberately customer-facing (FR-21) -- it must
    # reach the EXTERNAL model's tool-calling surface, not be excluded.
    ctx = RecordingCtx(profile="customer_service_external")
    register(ctx)
    assert "toee_customer_memory__get_my_memory_summary" in ctx.registered_names()


def test_register_supervisor_profile_excludes_customer_send_tools() -> None:
    ctx = RecordingCtx(profile="supervisor_admin")
    register(ctx)
    toolsets = ctx.registered_toolsets()
    assert toolsets == set(PROFILE_TOOL_ALLOWLIST["supervisor_admin"])
    assert "toee_textline_reply" not in toolsets
    assert "toee_square_payment_link" not in toolsets


def test_register_defaults_to_external_when_profile_absent(monkeypatch) -> None:
    monkeypatch.delenv("TOEE_HERMES_PROFILE", raising=False)
    ctx = RecordingCtx(profile=None)
    register(ctx)
    assert ctx.registered_toolsets() == set(PROFILE_TOOL_ALLOWLIST[DEFAULT_PROFILE])


def test_register_unknown_profile_raises() -> None:
    ctx = RecordingCtx(profile="bogus_profile")
    with pytest.raises(ValueError):
        register(ctx)


def test_registered_handler_is_callable_and_returns_json() -> None:
    ctx = RecordingCtx(profile="supervisor_admin")
    register(ctx)
    entry = next(
        tool
        for tool in ctx.tools
        if tool["name"] == "toee_workbench_admin__list_accounts"
    )
    assert json.loads(entry["handler"]({})) == {"accounts": []}
