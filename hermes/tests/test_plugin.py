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
    # register_turn is the live async SMS turn's entry point -- the actual
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


# --- 0.0.5 S11: erase_customer_memory is never LLM-callable (governance) ---


def test_erase_customer_memory_is_never_registered_as_an_llm_tool() -> None:
    # toee_customer_memory is allowlisted for BOTH external and internal_copilot,
    # and unexcluded actions ride the shared toolset registration onto every
    # profile the toolset is attached to -- so the erase has to be checked on
    # both, not just the admin one (FR-13, the get_memory_audit precedent).
    # A model that could call this would destroy, in one tool call, the data
    # every other governance surface in 0.0.5 exists to protect.
    for profile in ("customer_service_external", "internal_copilot"):
        ctx = RecordingCtx(profile=profile)
        register(ctx)
        assert "toee_customer_memory__erase_customer_memory" not in ctx.registered_names()


def test_erase_customer_memory_stays_excluded_on_register_turn_too() -> None:
    # register_turn is the live async SMS turn's entry point -- the production
    # path a prompt-injected customer message would actually try to exploit,
    # and the one register() alone does not cover (the link_identity precedent).
    ctx = RecordingCtx(profile="customer_service_external")
    register_turn(ctx, conversation_id="conv_1")
    assert "toee_customer_memory__erase_customer_memory" not in ctx.registered_names()


def test_erase_customer_memory_is_listed_in_the_exclusion_set() -> None:
    # The registration tests above prove the OUTCOME on the profiles that exist
    # today; this proves the MECHANISM, so a future profile gaining the toolset
    # cannot expose an action nobody excluded.
    assert ("toee_customer_memory", "erase_customer_memory") in _AGENT_EXCLUDED_ACTIONS


def test_clear_preference_stays_llm_callable_so_the_exclusion_is_not_blanket() -> None:
    # Contrast, so the three assertions above cannot pass by toee_customer_memory
    # having been excluded WHOLESALE. clear_preference is the customer's own
    # governed self-service clear (FR-21) and must keep reaching the model's
    # tool-calling surface; the erase is what does not.
    ctx = RecordingCtx(profile="customer_service_external")
    register(ctx)
    assert "toee_customer_memory__clear_preference" in ctx.registered_names()


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


# --- 0.0.5 S15: no review-inbox action is ever LLM-callable (governance) ---


def test_no_review_inbox_action_is_registered_as_an_llm_tool() -> None:
    # toee_review_inbox is allowlisted for internal_copilot only (re-classify
    # dispatches to L6 and L7, which live on that profile). EVERY action is
    # excluded, and the loop is derived from the catalog so a fifth action added
    # later cannot slip past by nobody remembering to add a line here -- the
    # "loop over every governed action that ran three of four" shape.
    #
    # propose_review_item is excluded for its own reason: it is the seam S10's
    # blast-radius pass, S20's sweep and S25's aggregator emit through, not an
    # admin action. A model that could raise its own review items would be
    # writing the queue that exists to check it.
    for profile in ("customer_service_external", "internal_copilot"):
        ctx = RecordingCtx(profile=profile)
        register(ctx)
        for action in TOOL_CATALOG["toee_review_inbox"]:
            assert f"toee_review_inbox__{action}" not in ctx.registered_names()


def test_every_review_inbox_action_is_listed_in_the_exclusion_set() -> None:
    # The registration test above proves the OUTCOME on the two profiles that
    # exist today; this proves the MECHANISM, so a future profile gaining the
    # toolset cannot expose an action nobody excluded.
    for action in TOOL_CATALOG["toee_review_inbox"]:
        assert ("toee_review_inbox", action) in _AGENT_EXCLUDED_ACTIONS


# --- 0.0.3 S26: get_aggregate_metrics is never LLM-callable (governance) ---


def test_get_aggregate_metrics_is_never_registered_as_an_llm_tool() -> None:
    # toee_metrics is allowlisted for internal_copilot only, and its SOLE action
    # get_aggregate_metrics is wholly excluded -- an admin-only read reached only
    # through the metrics panel's gated BFF dispatch (FR-28, the get_memory_audit
    # precedent). It must never reach the model's tool-calling surface.
    for profile in ("customer_service_external", "internal_copilot"):
        ctx = RecordingCtx(profile=profile)
        register(ctx)
        assert "toee_metrics__get_aggregate_metrics" not in ctx.registered_names()


# --- 0.0.3 S28: retention sweep actions are never LLM-callable (governance) -


def test_retention_actions_are_never_registered_as_llm_tools() -> None:
    # toee_retention is allowlisted for internal_copilot only, and BOTH of its
    # actions are wholly excluded -- an admin-triggered batch delete and its
    # read, reached only through the admin BFF's gated dispatch or the
    # schedulable CLI entrypoint (FR-30, the get_aggregate_metrics precedent).
    # Must never reach the model's tool-calling surface on any profile.
    for profile in ("customer_service_external", "internal_copilot"):
        ctx = RecordingCtx(profile=profile)
        register(ctx)
        assert "toee_retention__trigger_retention_sweep" not in ctx.registered_names()
        assert "toee_retention__get_retention_status" not in ctx.registered_names()


def test_agent_experience_is_not_registered_for_external_profile() -> None:
    # ADR-0034/35: toee_agent_experience is internal_copilot only.
    ctx = RecordingCtx(profile="customer_service_external")
    register(ctx)
    assert "toee_agent_experience" not in ctx.registered_toolsets()


# --- 0.0.3 S24: confirm/reject_experience are never LLM-callable (governance) -


def test_confirm_and_reject_experience_are_never_registered_as_llm_tools() -> None:
    # The human confirm gate (US23, FR-24): the model must never be able to
    # self-approve/-reject its own L6 proposals. Admin-only, reached only from
    # the admin BFF's gated dispatch.
    ctx = RecordingCtx(profile="internal_copilot")
    register(ctx)
    assert "toee_agent_experience__confirm_experience" not in ctx.registered_names()
    assert "toee_agent_experience__reject_experience" not in ctx.registered_names()


# --- 0.0.5 S01/S02: the L7 admin surface is never LLM-callable (governance) ---


def test_the_lexicon_admin_actions_are_never_registered_as_llm_tools() -> None:
    # The human gate (FR-3/FR-8), the confirm_experience precedent one layer up:
    # a model that could confirm its own L7 proposal -- or call add_lexicon_entry,
    # which lands a CONFIRMED row with no proposal step at all -- would make the
    # propose->confirm gate decorative and NFR-3 false. edit and retire carry the
    # same authority over live L7 content. list is admin-only for the
    # list_agent_experience reason. Reached only from the admin BFF's gated
    # dispatch, on every profile that could otherwise expose the toolset.
    for profile in ("customer_service_external", "internal_copilot"):
        ctx = RecordingCtx(profile=profile)
        register(ctx)
        names = ctx.registered_names()
        for action in (
            "list_lexicon_entries",
            "confirm_lexicon_entry",
            "reject_lexicon_entry",
            "retire_lexicon_entry",
            "edit_lexicon_entry",
            "add_lexicon_entry",
        ):
            assert f"toee_semantic_lexicon__{action}" not in names


def test_propose_lexicon_entry_stays_llm_callable_for_internal_copilot() -> None:
    # Contrast with the exclusions above: propose_lexicon_entry IS the governed
    # write S04's capture fork calls, exactly like propose_experience. If this
    # ever flips, L7 loses its only agent-side input.
    ctx = RecordingCtx(profile="internal_copilot")
    register(ctx)
    assert "toee_semantic_lexicon__propose_lexicon_entry" in ctx.registered_names()


def test_the_lexicon_admin_actions_stay_excluded_on_register_turn_too() -> None:
    # register_turn is the live async SMS turn's entry point -- the production
    # path a prompt-injected customer message would try to exploit.
    ctx = RecordingCtx(profile="customer_service_external")
    register_turn(ctx, conversation_id="conv_1")
    assert "toee_semantic_lexicon__add_lexicon_entry" not in ctx.registered_names()
    assert "toee_semantic_lexicon__confirm_lexicon_entry" not in ctx.registered_names()


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
    # An allowlisted toolset whose EVERY action is agent-excluded registers no
    # tool at all, so it never appears here (0.0.4 S05's toee_job_queue is the
    # first such toolset on this profile -- the dead-letter view is reached only
    # by the admin BFF's deterministic dispatch, never a model's tool loop).
    fully_excluded = {
        tool
        for tool in PROFILE_TOOL_ALLOWLIST["supervisor_admin"]
        if all(
            (tool, action) in _AGENT_EXCLUDED_ACTIONS for action in TOOL_CATALOG[tool]
        )
    }
    # 0.0.4 S15 adds toee_integrations -- also fully agent-excluded (its single
    # status read is admin-BFF-only, never a model tool loop).
    # 0.0.4 S02 adds toee_feedback -- also fully agent-excluded (all four
    # actions, including list_feedback, are admin-BFF/copilot-BFF-dispatch-only).
    assert fully_excluded == {"toee_job_queue", "toee_integrations", "toee_feedback"}
    assert toolsets == set(PROFILE_TOOL_ALLOWLIST["supervisor_admin"]) - fully_excluded
    assert "toee_sms_reply" not in toolsets
    assert "toee_square_payment_link" not in toolsets


# --- 0.0.4 S02: toee_feedback is never LLM-callable on any profile (ADR-0154) -


def test_toee_feedback_actions_are_never_registered_as_llm_tools() -> None:
    # toee_feedback is allowlisted on BOTH internal_copilot (the three write
    # actions) and supervisor_admin (list_feedback), but every one of its four
    # actions is in _AGENT_EXCLUDED_ACTIONS -- the governance guarantee this
    # slice exists to prove (ADR-0154 decision 3: dispatch-reachable, never
    # model-callable). It must never appear on either profile's tool-calling
    # surface, nor on the toolset level (a wholly-excluded toolset registers no
    # handler at all -- see _wholly_excluded_toolsets in test_copilot_turn.py).
    feedback_actions = TOOL_CATALOG["toee_feedback"]
    for profile in ("internal_copilot", "supervisor_admin"):
        ctx = RecordingCtx(profile=profile)
        register(ctx)
        assert "toee_feedback" not in ctx.registered_toolsets()
        for action in feedback_actions:
            assert f"toee_feedback__{action}" not in ctx.registered_names()


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
