// v1 Domain Adapter Tool catalog. One tool per integration with a fixed v1
// `action` enum per ADR-0059 and ADR-0070. The catalog lists every valid
// action for each tool; per-profile allowlisting and Tool Gate enforcement
// live in @toee/domain-adapters.
export const TOOL_CATALOG = {
  toee_identity_lookup: [
    "match_phone",
    "match_email_sender",
    "get_email_link_status",
  ],
  toee_knowledge_search: ["search_public_site", "search_operational_policy"],
  toee_shopify_read: [
    "get_order",
    "list_customer_orders",
    "search_products",
    "get_product",
  ],
  toee_qbo_read: ["get_invoice", "list_customer_invoices", "get_ar_summary"],
  toee_easyroutes_read: ["get_delivery_status", "get_route_details"],
  toee_square_payment_link: ["send_payment_link"],
  toee_textline_reply: ["send_message"],
  toee_case: ["create_case", "update_case"],
  toee_customer_memory: [
    "upsert_preference",
    "clear_preference",
    "get_preferences",
  ],
  toee_case_manage: [
    "claim_case",
    "assign_case",
    "update_priority",
    "update_contact_reason",
    "resolve_case",
  ],
  toee_copilot_draft: ["draft_sms", "draft_email", "draft_internal_note"],
  toee_workbench_read: ["get_case", "list_cases", "get_audit_log"],
  toee_knowledge_ops: [
    "get_policy_slots",
    "update_policy_slot",
    "submit_for_eval",
    "rollback_published_policy",
  ],
  toee_eval_review: [
    "list_eval_runs",
    "get_eval_run",
    "sign_off_medium_failure",
    "promote_pending_policy",
  ],
  toee_workbench_admin: [
    "list_accounts",
    "create_account",
    "update_account_role",
    "disable_account",
  ],
} as const satisfies Record<string, readonly string[]>;

export type ToolName = keyof typeof TOOL_CATALOG;

export type ToolAction<T extends ToolName = ToolName> =
  (typeof TOOL_CATALOG)[T][number];

export const TOOL_NAMES = Object.keys(TOOL_CATALOG) as ToolName[];

export function isToolName(value: string): value is ToolName {
  return Object.prototype.hasOwnProperty.call(TOOL_CATALOG, value);
}

export function isToolAction(tool: ToolName, action: string): boolean {
  const actions: readonly string[] = TOOL_CATALOG[tool];
  return actions.includes(action);
}
