import type { MockHandlerRegistry } from "./mock-driver";

function readStringParam(
  params: Record<string, unknown>,
  key: string,
  fallback: string,
): string {
  const value = params[key];
  return typeof value === "string" ? value : fallback;
}

// Deterministic, no-op stub handlers for the Copilot and Supervisor Admin tools
// (ADR-0065 case manage, ADR-0067 copilot draft, ADR-0068 workbench read,
// ADR-0069 admin governance). Each action returns a minimal, structurally usable
// shape so later BFF slices can call it without inventing new mock contracts.
// These stubs make no external calls, use no clocks or randomness, and do not
// persist writes; the resource-oriented BFF slices replace them with real reads
// and governed writes.
export const adminStubMockHandlers: MockHandlerRegistry = {
  toee_workbench_read: {
    get_case: (params) => ({
      caseId: readStringParam(params, "caseId", "case_stub"),
      status: "open",
    }),
    list_cases: () => ({ cases: [] }),
    get_audit_log: (params) => ({
      caseId: readStringParam(params, "caseId", "case_stub"),
      entries: [],
    }),
    get_thread: (params) => ({
      caseId: readStringParam(params, "caseId", "case_stub"),
      messages: [],
    }),
    list_auto_handled: () => ({ records: [] }),
    get_auto_handled: () => ({ record: null }),
    list_sales_outreach: () => ({ cases: [] }),
    get_sales_outreach: () => ({ case: null }),
  },
  toee_case_manage: {
    claim_case: (params) => ({
      caseId: readStringParam(params, "caseId", "case_stub"),
      claimed: true,
    }),
    assign_case: (params) => ({
      caseId: readStringParam(params, "caseId", "case_stub"),
      assigneeId: readStringParam(params, "assigneeId", "account_stub"),
      assigned: true,
    }),
    update_priority: (params) => ({
      caseId: readStringParam(params, "caseId", "case_stub"),
      priority: readStringParam(params, "priority", "normal"),
      updated: true,
    }),
    update_contact_reason: (params) => ({
      caseId: readStringParam(params, "caseId", "case_stub"),
      contactReason: readStringParam(params, "contactReason", "general"),
      updated: true,
    }),
    resolve_case: (params) => ({
      caseId: readStringParam(params, "caseId", "case_stub"),
      status: "resolved",
    }),
    send_sms_message: (params) => ({
      message: {
        messageId: "msg_stub",
        conversationId: readStringParam(params, "caseId", "thread_stub"),
        body: readStringParam(params, "body", ""),
      },
    }),
  },
  toee_copilot_draft: {
    draft_sms: () => ({ channel: "sms", draft: "[stub SMS draft]" }),
    draft_email: () => ({
      channel: "email",
      subject: "[stub subject]",
      draft: "[stub email draft]",
    }),
    draft_internal_note: () => ({
      kind: "internal_note",
      draft: "[stub internal note]",
    }),
  },
  toee_knowledge_ops: {
    get_policy_slots: () => ({ slots: [] }),
    update_policy_slot: (params) => ({
      slot: readStringParam(params, "slot", "slot_stub"),
      state: "draft",
      updated: true,
    }),
    submit_for_eval: () => ({ submitted: true, status: "pending_eval" }),
    rollback_published_policy: (params) => ({
      slot: readStringParam(params, "slot", "slot_stub"),
      rolledBack: true,
    }),
  },
  toee_eval_review: {
    list_eval_runs: () => ({ runs: [] }),
    get_eval_run: (params) => ({
      runId: readStringParam(params, "runId", "run_stub"),
      status: "passed",
    }),
    sign_off_medium_failure: (params) => ({
      runId: readStringParam(params, "runId", "run_stub"),
      signedOff: true,
    }),
    promote_pending_policy: (params) => ({
      slot: readStringParam(params, "slot", "slot_stub"),
      promoted: true,
      status: "published",
    }),
  },
  toee_workbench_admin: {
    list_accounts: () => ({ accounts: [] }),
    create_account: () => ({ accountId: "account_stub", created: true }),
    update_account_role: (params) => ({
      accountId: readStringParam(params, "accountId", "account_stub"),
      role: readStringParam(params, "role", "customer_service_rep"),
      updated: true,
    }),
    disable_account: (params) => ({
      accountId: readStringParam(params, "accountId", "account_stub"),
      disabled: true,
    }),
    // Deterministic no-op (ADR-0144): the mock verifies nothing and is never an
    // auth authority — a real login surface must run TOOL_BACKEND=datastore.
    authenticate: (params) => ({
      account: {
        accountId: readStringParam(params, "username", "account_stub"),
        role: "customer_service_rep",
        status: "active",
      },
    }),
  },
};
