"""Mock STUB handlers for the Copilot/Supervisor-Admin tools (ports mock/admin-stubs.ts).

Deterministic no-op stubs for the six Copilot/Admin tools: case manage
(ADR-0065), copilot draft (ADR-0067), workbench read (ADR-0068), admin
governance (ADR-0069), plus knowledge ops and eval review. Every v1 catalog
action is exercised through ``execute_tool`` so the governed boundary is covered
end-to-end, and the registry is asserted to cover every action so later BFF
slices can call them. Output keys are snake_case (the TS catalog's camelCase is
converted) and inputs are read snake_case-first with a camelCase fallback.
"""

import pytest

from toee_hermes.drivers.mock.admin_stubs import create_admin_stub_mock_handlers
from toee_hermes.drivers.mock.driver import MockDriver
from toee_hermes.execute import execute_tool
from toee_hermes.operational_policy import REQUIRED_POLICY_SLOTS
from toee_hermes.tool_catalog import TOOL_CATALOG
from toee_hermes.tool_gate import ToolExecutionContext

# The six Copilot/Supervisor-Admin tools these stubs cover (mirrors the TS test).
STUB_TOOLS = (
    "toee_workbench_read",
    "toee_case_manage",
    "toee_copilot_draft",
    "toee_knowledge_ops",
    "toee_eval_review",
    "toee_workbench_admin",
    # 0.0.4 S05 (FR-13): the dead-letter view. Postgres-only tables behind it, so
    # the twin reports an honest empty view / "unavailable" replay receipt.
    "toee_job_queue",
    # 0.0.4 S15 (FR-23): the /admin/integrations status read. Live config presence
    # is the datastore handler's job; the mock twin reports every integration
    # not_configured with an honest reason, never a fabricated "healthy".
    "toee_integrations",
)

# A superset of the snake_case identifiers any stub action might echo back.
ACTION_PARAMS = {
    "case_id": "c1",
    "assignee_id": "u1",
    "slot": "s1",
    "run_id": "r1",
    "account_id": "a1",
}

ALL_STUB_ACTIONS = [
    (tool, action) for tool in STUB_TOOLS for action in TOOL_CATALOG[tool]
]


def _driver() -> MockDriver:
    return MockDriver(create_admin_stub_mock_handlers())


def _ctx() -> ToolExecutionContext:
    # Supervisor Admin is the broadest profile; the stubs ignore context anyway.
    return ToolExecutionContext(profile="supervisor_admin")


def _call(tool: str, action: str, params: dict | None = None):
    return execute_tool(
        tool=tool,
        action=action,
        params=params or {},
        context=_ctx(),
        driver=_driver(),
    )


@pytest.mark.parametrize("tool,action", ALL_STUB_ACTIONS)
def test_every_stub_action_is_callable_and_deterministic(tool: str, action: str) -> None:
    # Each catalog action dispatches through the governed boundary and returns a
    # deterministic dict (no clock/randomness), so calling twice is identical.
    first = _call(tool, action, dict(ACTION_PARAMS))
    second = _call(tool, action, dict(ACTION_PARAMS))

    assert first.ok is True
    assert second.ok is True
    assert isinstance(first.data, dict)
    assert first.data == second.data


def test_registry_covers_exactly_the_stub_tools_and_all_catalog_actions() -> None:
    registry = create_admin_stub_mock_handlers()

    assert set(registry) == set(STUB_TOOLS)
    for tool in STUB_TOOLS:
        assert set(registry[tool]) == set(TOOL_CATALOG[tool]), tool


# --- Representative shape per tool (snake_case output, snake_case input) -------


def test_workbench_read_get_case_echoes_case_id_with_open_status() -> None:
    result = _call("toee_workbench_read", "get_case", {"case_id": "case_1"})

    assert result.ok is True
    assert result.data == {"case_id": "case_1", "status": "open"}


def test_workbench_read_get_case_reads_camelcase_fallback() -> None:
    result = _call("toee_workbench_read", "get_case", {"caseId": "case_2"})

    assert result.data == {"case_id": "case_2", "status": "open"}


def test_workbench_read_get_case_defaults_to_stub_when_absent() -> None:
    result = _call("toee_workbench_read", "get_case")

    assert result.data == {"case_id": "case_stub", "status": "open"}


def test_case_manage_assign_case_reports_snake_case_ids() -> None:
    result = _call(
        "toee_case_manage",
        "assign_case",
        {"case_id": "c9", "assignee_id": "u9"},
    )

    assert result.ok is True
    assert result.data == {
        "case_id": "c9",
        "assignee_id": "u9",
        "assigned": True,
    }


def test_case_manage_update_contact_reason_uses_snake_case_key() -> None:
    result = _call(
        "toee_case_manage",
        "update_contact_reason",
        {"case_id": "c1", "contact_reason": "billing"},
    )

    assert result.data == {
        "case_id": "c1",
        "contact_reason": "billing",
        "updated": True,
    }


def test_copilot_draft_sms_returns_stub_draft_string() -> None:
    result = _call("toee_copilot_draft", "draft_sms")

    assert result.ok is True
    assert result.data == {"channel": "sms", "draft": "[stub SMS draft]"}
    assert isinstance(result.data["draft"], str)


def test_knowledge_ops_get_policy_slots_returns_six_required_placeholders() -> None:
    # ADR-0003: the six Required Operational Policy Slots exist as structured
    # placeholders at onboarding (empty content until KnowledgeOps publishes copy).
    result = _call("toee_knowledge_ops", "get_policy_slots")

    assert result.ok is True
    slots = result.data["slots"]
    assert [slot["key"] for slot in slots] == list(REQUIRED_POLICY_SLOTS)
    assert all(slot["status"] == "empty" and slot["content"] == "" for slot in slots)


def test_knowledge_ops_rollback_uses_rolled_back_key() -> None:
    result = _call("toee_knowledge_ops", "rollback_published_policy", {"slot": "s1"})

    assert result.data == {"slot": "s1", "rolled_back": True}


def test_eval_review_get_eval_run_echoes_run_id() -> None:
    result = _call("toee_eval_review", "get_eval_run", {"run_id": "r1"})

    assert result.ok is True
    assert result.data == {"run_id": "r1", "status": "passed"}


def test_eval_review_sign_off_uses_signed_off_key() -> None:
    result = _call("toee_eval_review", "sign_off_medium_failure", {"run_id": "r1"})

    assert result.data == {"run_id": "r1", "signed_off": True}


def test_workbench_admin_list_accounts_returns_empty_list() -> None:
    result = _call("toee_workbench_admin", "list_accounts")

    assert result.ok is True
    assert result.data == {"accounts": []}


def test_workbench_admin_create_account_returns_account_id_stub() -> None:
    result = _call("toee_workbench_admin", "create_account")

    assert result.data == {"account_id": "account_stub", "created": True}
