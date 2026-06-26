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
from toee_hermes.plugin import register
from toee_hermes.plugin.profiles import DEFAULT_PROFILE, PROFILE_TOOL_ALLOWLIST
from toee_hermes.plugin.schemas import build_tool_schemas, hermes_tool_name
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
    expected = sum(
        len(TOOL_CATALOG[tool])
        for tool in PROFILE_TOOL_ALLOWLIST["customer_service_external"]
    )
    assert len(ctx.tools) == expected
    assert ctx.hook_events() == ["pre_llm_call"]


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
