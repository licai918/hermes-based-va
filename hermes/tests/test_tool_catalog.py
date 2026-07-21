"""v1 Domain Adapter Tool catalog (ADR-0059, ADR-0070).

Ports the membership semantics of the TS `@toee/shared` catalog: one tool per
integration with a fixed v1 action enum; per-profile allowlisting and Tool Gate
enforcement live elsewhere.
"""

from toee_hermes.tool_catalog import (
    TOOL_CATALOG,
    is_tool_action,
    is_tool_name,
    tool_names,
)


def test_catalog_lists_every_v1_tool() -> None:
    assert set(tool_names()) == {
        "toee_identity_lookup",
        "toee_knowledge_search",
        "toee_shopify_read",
        "toee_qbo_read",
        "toee_easyroutes_read",
        "toee_square_payment_link",
        "toee_textline_reply",
        "toee_case",
        "toee_customer_memory",
        "toee_case_manage",
        "toee_copilot_draft",
        "toee_workbench_read",
        "toee_knowledge_ops",
        "toee_eval_review",
        "toee_workbench_admin",
        "toee_agent_experience",
        "toee_metrics",
    }


def test_agent_experience_actions_match_fr_23() -> None:
    # 0.0.3 S22 (FR-23): the L6 Agent-experience store's governed write
    # (propose_experience) and its admin-only read (list_agent_experience,
    # excluded from the LLM tool-calling loop -- see
    # toee_hermes.plugin._AGENT_EXCLUDED_ACTIONS). 0.0.3 S24 (FR-24) adds the
    # human confirm-gate decision actions, also excluded.
    assert TOOL_CATALOG["toee_agent_experience"] == (
        "propose_experience",
        "list_agent_experience",
        "confirm_experience",
        "reject_experience",
    )
    assert is_tool_action("toee_agent_experience", "propose_experience") is True
    assert is_tool_action("toee_agent_experience", "list_agent_experience") is True
    assert is_tool_action("toee_agent_experience", "confirm_experience") is True
    assert is_tool_action("toee_agent_experience", "reject_experience") is True


def test_metrics_actions_match_fr_28() -> None:
    # 0.0.3 S26 (FR-28): the aggregate-metrics admin panel's single read-only
    # action, excluded from the LLM tool-calling loop (see
    # toee_hermes.plugin._AGENT_EXCLUDED_ACTIONS), same precedent as
    # get_memory_audit/list_agent_experience.
    assert TOOL_CATALOG["toee_metrics"] == ("get_aggregate_metrics",)
    assert is_tool_action("toee_metrics", "get_aggregate_metrics") is True


def test_identity_lookup_actions_match_adr_0060() -> None:
    assert TOOL_CATALOG["toee_identity_lookup"] == (
        "match_phone",
        "match_email_sender",
        "get_email_link_status",
        # 0.0.3 S05 (FR-13): explicit Identity Graph link, used by the
        # Conversation Simulator's "link identity" control -- see
        # hermes-runtime/hermes_runtime/datastore/handlers/identity.py.
        "link_identity",
    )


def test_workbench_read_exposes_get_thread_for_case_thread_context() -> None:
    # ADR-0143 extends ADR-0068 with the Case Thread Context read; 0.0.3 S02 adds
    # get_thread_by_phone for the Conversation Simulator's read-back (FR-9), which
    # has no case_id to key off until the gateway's async webhook creates one.
    # 0.0.3 S18 adds get_thread_by_email, the same read-back shape for the
    # simulator's email channel switcher (FR-11).
    assert TOOL_CATALOG["toee_workbench_read"] == (
        "get_case",
        "list_cases",
        "get_audit_log",
        "get_thread",
        "get_thread_by_phone",
        "get_thread_by_email",
        "list_auto_handled",
        "get_auto_handled",
        "list_sales_outreach",
        "get_sales_outreach",
    )
    assert is_tool_action("toee_workbench_read", "get_thread") is True
    assert is_tool_action("toee_workbench_read", "get_thread_by_phone") is True
    assert is_tool_action("toee_workbench_read", "get_thread_by_email") is True
    assert is_tool_action("toee_workbench_read", "list_auto_handled") is True


def test_workbench_admin_exposes_authenticate_for_login_cutover() -> None:
    # ADR-0144 extends ADR-0069 with the server-side login verification action.
    assert TOOL_CATALOG["toee_workbench_admin"] == (
        "list_accounts",
        "create_account",
        "update_account_role",
        "disable_account",
        "authenticate",
    )
    assert is_tool_action("toee_workbench_admin", "authenticate") is True


def test_is_tool_name_accepts_known_and_rejects_unknown() -> None:
    assert is_tool_name("toee_identity_lookup") is True
    assert is_tool_name("toee_unknown") is False


def test_is_tool_action_is_scoped_to_its_tool() -> None:
    assert is_tool_action("toee_identity_lookup", "match_phone") is True
    # Valid action, but belongs to a different tool.
    assert is_tool_action("toee_identity_lookup", "get_order") is False


def test_is_tool_action_false_for_unknown_tool() -> None:
    assert is_tool_action("toee_unknown", "match_phone") is False
