"""v1 Domain Adapter Tool catalog (ADR-0059, ADR-0070).

One tool per integration with a fixed v1 ``action`` enum. The catalog lists every
valid action for each tool; per-profile allowlisting and Tool Gate enforcement
live in :mod:`toee_hermes.tool_gate` and the dispatch layer. Ported from the TS
``@toee/shared`` catalog so both runtimes share one source of truth.
"""

from __future__ import annotations

# Insertion order is preserved and mirrors the TS catalog.
TOOL_CATALOG: dict[str, tuple[str, ...]] = {
    "toee_identity_lookup": (
        "match_phone",
        "match_email_sender",
        "get_email_link_status",
    ),
    "toee_knowledge_search": ("search_public_site", "search_operational_policy"),
    "toee_shopify_read": (
        "get_order",
        "list_customer_orders",
        "search_products",
        "get_product",
    ),
    "toee_qbo_read": ("get_invoice", "list_customer_invoices", "get_ar_summary"),
    "toee_easyroutes_read": ("get_delivery_status", "get_route_details"),
    "toee_square_payment_link": ("send_payment_link",),
    "toee_sms_reply": ("send_message",),
    "toee_case": ("create_case", "update_case"),
    "toee_customer_memory": (
        "upsert_preference",
        "clear_preference",
        "get_preferences",
    ),
    "toee_case_manage": (
        "claim_case",
        "assign_case",
        "update_priority",
        "update_contact_reason",
        "resolve_case",
        "send_sms_message",
    ),
    "toee_copilot_draft": ("draft_sms", "draft_email", "draft_internal_note"),
    "toee_workbench_read": ("get_case", "list_cases", "get_audit_log", "get_thread", "list_auto_handled", "get_auto_handled", "list_sales_outreach", "get_sales_outreach"),
    "toee_knowledge_ops": (
        "get_policy_slots",
        "update_policy_slot",
        "submit_for_eval",
        "rollback_published_policy",
    ),
    "toee_eval_review": (
        "list_eval_runs",
        "get_eval_run",
        "sign_off_medium_failure",
        "promote_pending_policy",
    ),
    "toee_workbench_admin": (
        "list_accounts",
        "create_account",
        "update_account_role",
        "disable_account",
        "authenticate",
    ),
}


def tool_names() -> list[str]:
    """Return the v1 tool names in catalog order."""
    return list(TOOL_CATALOG)


def is_tool_name(value: str) -> bool:
    """True when ``value`` is a known v1 tool."""
    return value in TOOL_CATALOG


def is_tool_action(tool: str, action: str) -> bool:
    """True when ``action`` is valid for ``tool`` (and ``tool`` is known)."""
    actions = TOOL_CATALOG.get(tool)
    return actions is not None and action in actions
