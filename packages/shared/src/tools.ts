// The Toee tool catalog: one tool per integration or governed store, each with a
// fixed `action` enum (ADR-0059, ADR-0070). Per-profile allowlisting and Tool
// Gate enforcement live in the Python per-profile dispatch servers
// (hermes-runtime's tool_dispatch_app.py / tool_dispatch_composition.py), since
// 0.0.4 S11 deleted @toee/domain-adapters (ADR-0156).
//
// THE RULE, so you do not have to guess: this file is an EXACT MIRROR of
// hermes/toee_hermes/tool_catalog.py -- same tools, same actions, no subset, no
// exceptions. `hermes/tests/test_tool_catalog_parity.py` reads this file and
// fails the build on any divergence. Add a tool or an action to both, or to
// neither.
//
// It has not always been a mirror, and the drift is why the parity test exists.
// The header used to say "v1 Domain Adapter Tool catalog", which sounded like it
// licensed a subset -- but post-v1 governed stores (toee_agent_experience,
// toee_feedback, toee_semantic_lexicon) were added anyway, so the stated scope
// stopped describing the contents and nobody could tell what belonged. Meanwhile
// five whole tools and six actions had gone missing on this side, invisible
// because the only test guarding the file compared it to a hardcoded copy of
// itself. Backfilled and made exact in 0.0.5.
export const TOOL_CATALOG = {
  toee_identity_lookup: [
    "match_phone",
    "match_email_sender",
    "get_email_link_status",
    "link_identity",
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
  // 0.0.4 delivery initiative: Tier-1 fulfillment, Tier-3a customer promise and
  // Tier-3b public prospect quote.
  toee_delivery_promise: [
    "get_order_delivery",
    "get_product_promise",
    "get_delivery_quote",
  ],
  toee_square_payment_link: ["send_payment_link"],
  toee_sms_reply: ["send_message"],
  toee_case: ["create_case", "update_case"],
  // L4 Customer Memory. The write pair is governed (ADR-0148: framework-derived
  // source and actor, context-only binding); get_my_memory_summary and
  // dismiss_proposal are the customer's own self-service reads, and
  // get_memory_audit is the supervisor's. erase_customer_memory (0.0.5 S11,
  // FR-13) is the supervisor's whole-binding erase -- agent-excluded on the
  // Python side, reached only from the Memory Audit console's BFF dispatch.
  toee_customer_memory: [
    "upsert_preference",
    "clear_preference",
    "erase_customer_memory",
    "get_preferences",
    "get_my_memory_summary",
    "dismiss_proposal",
    "get_memory_audit",
  ],
  toee_case_manage: [
    "claim_case",
    "assign_case",
    "update_priority",
    "update_contact_reason",
    "resolve_case",
    "send_sms_message",
  ],
  toee_copilot_draft: ["draft_sms", "draft_email", "draft_internal_note"],
  toee_workbench_read: [
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
  ],
  toee_knowledge_ops: [
    "get_policy_slots",
    "update_policy_slot",
    "submit_for_eval",
    "rollback_published_policy",
    "get_corpus_status",
    "enqueue_corpus_reingest",
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
    "authenticate",
  ],
  // 0.0.3 S22 (FR-23, NFR-3): L6 Agent-experience store -- see
  // hermes/toee_hermes/tool_catalog.py for the full rationale. 0.0.3 S24
  // (FR-24) adds confirm_experience/reject_experience, the human confirm gate.
  toee_agent_experience: [
    "propose_experience",
    "list_agent_experience",
    "confirm_experience",
    "reject_experience",
  ],
  // 0.0.5 S01 (FR-1/FR-3): L7 Semantic Lexicon store -- see
  // hermes/toee_hermes/tool_catalog.py for the full rationale.
  // propose_lexicon_entry writes status='proposed' only; list_lexicon_entries is
  // agent-excluded on the Python side (admin BFF dispatch only). 0.0.5 S02
  // (FR-3 decide side/FR-8) adds the human gate: confirm/reject/retire flip
  // status, edit_lexicon_entry is D7's in-place mapping update (stable id), and
  // add_lexicon_entry lands the admin's own entry already confirmed. All five
  // are agent-excluded on the Python side too -- admin BFF dispatch only.
  toee_semantic_lexicon: [
    "propose_lexicon_entry",
    "list_lexicon_entries",
    "confirm_lexicon_entry",
    "reject_lexicon_entry",
    "retire_lexicon_entry",
    "edit_lexicon_entry",
    "add_lexicon_entry",
  ],
  // 0.0.5 S15 (FR-22): the unified review inbox + its `review_item` store --
  // see hermes/toee_hermes/tool_catalog.py for the full rationale. The store
  // exists because S10/S20/S25 all emit inbox items and none of them defines
  // storage. 0.0.5 S10 (FR-12) adds get_blast_radius, the admin read behind the
  // blast_radius item: which turns/cases a memory entry reached, from the S09
  // injection ledger joined to case status. Every action is agent-excluded on
  // the Python side (admin BFF dispatch, or a scheduled job's own dispatch,
  // only).
  toee_review_inbox: [
    "propose_review_item",
    "list_review_items",
    "decide_review_item",
    "reclassify_proposal",
    "get_blast_radius",
  ],
  // 0.0.4 operations surfaces. Agent-excluded on the Python side: reachable by
  // the admin/supervisor dispatch profiles, never model-callable.
  toee_metrics: ["get_aggregate_metrics"],
  toee_retention: [
    "trigger_retention_sweep",
    "enqueue_retention_sweep",
    "get_retention_status",
  ],
  toee_job_queue: ["list_dead_letters", "replay_job"],
  toee_integrations: [
    "get_integrations_status",
    "initiate_reconnect",
    "reprobe_now",
  ],
  // 0.0.4 S02 (ADR-0154): the manual scoring feedback tool shell -- see
  // hermes/toee_hermes/tool_catalog.py for the full rationale. Fixed
  // four-action enum. Every action is agent-excluded on the Python side, so it
  // is dispatch-reachable (internal_copilot + supervisor_admin) but never
  // model-callable.
  toee_feedback: [
    "submit_interaction_review",
    "record_draft_outcome",
    "submit_draft_rating",
    "list_feedback",
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
