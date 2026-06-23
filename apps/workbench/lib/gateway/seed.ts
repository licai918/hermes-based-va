// Deterministic demo seed for the in-memory GatewayStore. Fixed timestamps (no
// clock/randomness) so the Copilot Workbench renders a stable, review-friendly
// queue in local dev and tests. Mirrors the launch-eval spirit: a verified AR
// case, an unmatched caller, a non-customer intake, a tool-failure escalation, a
// sales-outreach record, a resolved case, plus auto-handled audit samples.
import type {
  AuditLogEntry,
  AutoHandledRecord,
  ThreadMessage,
  WorkbenchCase,
} from "./types";
import type { GatewayStoreSeed } from "./store";

const HOUR = 60 * 60 * 1000;
// Anchored, fixed "now" for the seed (2026-06-01T12:00:00Z). Cases open at
// negative offsets from this so ordering is stable across runs.
const NOW = Date.UTC(2026, 5, 1, 12, 0, 0);

function msg(
  threadId: string,
  partial: Partial<ThreadMessage> & { messageId: string; at: number; author: ThreadMessage["author"]; body: string },
): ThreadMessage {
  return {
    threadId,
    channel: "sms",
    autoHandled: false,
    activeCaseSegment: true,
    ...partial,
  };
}

const cases: WorkbenchCase[] = [
  {
    caseId: "case_ar_urgent",
    channel: "sms",
    identitySummary: "Verified: Westside Auto (acct 4471)",
    contactReason: "order_status",
    urgent: true,
    status: "open",
    assigneeAccountId: null,
    resolvedByAccountId: null,
    threadId: "thread_ar",
    lastMessagePreview: "Any update on my delivery? I need the tires today.",
    toolFailure: false,
    smsSessionActive: true,
    openedAt: NOW - 6 * HOUR,
    lastActivityAt: NOW - 1 * HOUR,
  },
  {
    caseId: "case_toolfail",
    channel: "sms",
    identitySummary: "Verified: North Tire Co (acct 2210)",
    contactReason: "billing",
    urgent: true,
    status: "open",
    assigneeAccountId: null,
    resolvedByAccountId: null,
    threadId: "thread_toolfail",
    lastMessagePreview: "Can you send my current balance?",
    toolFailure: true,
    smsSessionActive: true,
    openedAt: NOW - 3 * HOUR,
    lastActivityAt: NOW - 2 * HOUR,
  },
  {
    caseId: "case_unmatched",
    channel: "sms",
    identitySummary: "Unmatched caller (+1 ••• 4821)",
    contactReason: "unknown",
    urgent: false,
    status: "open",
    assigneeAccountId: null,
    resolvedByAccountId: null,
    threadId: "thread_unmatched",
    lastMessagePreview: "What's the status of order 10293?",
    toolFailure: false,
    smsSessionActive: true,
    openedAt: NOW - 8 * HOUR,
    lastActivityAt: NOW - 5 * HOUR,
  },
  {
    caseId: "case_billing_email",
    channel: "email",
    identitySummary: "Verified: Jane's Garage",
    contactReason: "billing",
    urgent: false,
    status: "in_progress",
    assigneeAccountId: "seed-rep",
    resolvedByAccountId: null,
    threadId: "thread_billing",
    lastMessagePreview: "Re: invoice INV-8841 — can we split this payment?",
    toolFailure: false,
    smsSessionActive: false,
    openedAt: NOW - 10 * HOUR,
    lastActivityAt: NOW - 4 * HOUR,
  },
  {
    caseId: "case_gov",
    channel: "email",
    identitySummary: "Non-customer: City of Riverside (procurement)",
    contactReason: "government",
    urgent: false,
    status: "open",
    assigneeAccountId: null,
    resolvedByAccountId: null,
    threadId: "thread_gov",
    lastMessagePreview: "RFQ for fleet tires — who is our account contact?",
    toolFailure: false,
    smsSessionActive: false,
    openedAt: NOW - 26 * HOUR,
    lastActivityAt: NOW - 20 * HOUR,
  },
  {
    caseId: "case_resolved",
    channel: "sms",
    identitySummary: "Verified: Hilltop Motors",
    contactReason: "order_status",
    urgent: false,
    status: "resolved",
    assigneeAccountId: "seed-rep",
    resolvedByAccountId: "seed-rep",
    threadId: "thread_resolved",
    lastMessagePreview: "Thanks, got it!",
    toolFailure: false,
    smsSessionActive: false,
    openedAt: NOW - 30 * HOUR,
    lastActivityAt: NOW - 28 * HOUR,
  },
  {
    caseId: "case_sales",
    channel: "email",
    identitySummary: "Non-customer: BrightAds Media",
    contactReason: "sales_outreach",
    urgent: false,
    status: "open",
    assigneeAccountId: null,
    resolvedByAccountId: null,
    threadId: "thread_sales",
    lastMessagePreview: "Partnership opportunity for your marketing…",
    toolFailure: false,
    smsSessionActive: false,
    openedAt: NOW - 12 * HOUR,
    lastActivityAt: NOW - 12 * HOUR,
  },
];

const threads: Record<string, ThreadMessage[]> = {
  thread_ar: [
    msg("thread_ar", { messageId: "ar_1", at: NOW - 30 * HOUR, author: "customer", body: "Hi, I ordered 4 tires last week (order 10311).", autoHandled: true, activeCaseSegment: false }),
    msg("thread_ar", { messageId: "ar_2", at: NOW - 30 * HOUR + 60_000, author: "hermes", body: "Thanks! Your order 10311 shipped and is out for delivery today.", autoHandled: true, activeCaseSegment: false }),
    msg("thread_ar", { messageId: "ar_3", at: NOW - 6 * HOUR, author: "customer", body: "It hasn't arrived. Any update on my delivery? I need the tires today." }),
    msg("thread_ar", { messageId: "ar_4", at: NOW - 1 * HOUR, author: "hermes", body: "I've flagged this for a team member to check the route status and follow up." }),
  ],
  thread_toolfail: [
    msg("thread_toolfail", { messageId: "tf_1", at: NOW - 3 * HOUR, author: "customer", body: "Can you send my current balance?" }),
    msg("thread_toolfail", { messageId: "tf_2", at: NOW - 2 * HOUR, author: "hermes", body: "Our accounting system is temporarily unavailable, so I've opened a case for a team member to confirm your balance." }),
  ],
  thread_unmatched: [
    msg("thread_unmatched", { messageId: "um_1", at: NOW - 8 * HOUR, author: "customer", body: "What's the status of order 10293?" }),
    msg("thread_unmatched", { messageId: "um_2", at: NOW - 5 * HOUR, author: "hermes", body: "I can't verify this number against an account here, so I've opened a case for the team to verify and follow up. Could you share your order number?" }),
  ],
  thread_billing: [
    msg("thread_billing", { messageId: "bl_1", at: NOW - 10 * HOUR, author: "customer", channel: "email", body: "Re: invoice INV-8841 — can we split this payment?" }),
    msg("thread_billing", { messageId: "bl_2", at: NOW - 4 * HOUR, author: "workbench", channel: "email", body: "Looking into payment options for INV-8841." }),
  ],
  thread_gov: [
    msg("thread_gov", { messageId: "gv_1", at: NOW - 26 * HOUR, author: "customer", channel: "email", body: "RFQ for fleet tires — who is our account contact?" }),
  ],
  thread_sales: [
    msg("thread_sales", { messageId: "sa_1", at: NOW - 12 * HOUR, author: "customer", channel: "email", body: "Partnership opportunity for your marketing…" }),
    msg("thread_sales", { messageId: "sa_2", at: NOW - 12 * HOUR + 60_000, author: "hermes", channel: "email", body: "Thanks for reaching out — we're not pursuing new marketing partnerships right now." }),
  ],
};

const auditLog: AuditLogEntry[] = [
  { entryId: "seed_audit_1", at: NOW - 4 * HOUR, actorAccountId: "seed-rep", actorUsername: "rep", action: "case_view", caseId: "case_billing_email" },
  { entryId: "seed_audit_2", at: NOW - 4 * HOUR + 30_000, actorAccountId: "seed-rep", actorUsername: "rep", action: "draft_generated", caseId: "case_billing_email", detail: "draft_email" },
];

const autoHandled: AutoHandledRecord[] = [
  {
    recordId: "ah_order_status",
    channel: "sms",
    identitySummary: "Verified: Lakeside Auto",
    lastMessagePreview: "Perfect, thank you!",
    lastActivityAt: NOW - 2 * HOUR,
    outcome: "auto_resolved",
    toolSummary: "match_phone, get_order, get_delivery_status",
    toolFailure: false,
    timeline: [
      msg("ah_order_status", { messageId: "aho_1", at: NOW - 3 * HOUR, author: "customer", body: "Where is order 10422?", autoHandled: true }),
      msg("ah_order_status", { messageId: "aho_2", at: NOW - 3 * HOUR + 45_000, author: "hermes", body: "Order 10422 is out for delivery and should arrive today.", autoHandled: true }),
      msg("ah_order_status", { messageId: "aho_3", at: NOW - 2 * HOUR, author: "customer", body: "Perfect, thank you!", autoHandled: true }),
    ],
    toolCalls: [
      { tool: "toee_identity_lookup", action: "match_phone", inputSummary: "phone +1•••7782", outputSummary: "matched customer Lakeside Auto" },
      { tool: "toee_shopify_read", action: "get_order", inputSummary: "order 10422", outputSummary: "status: out_for_delivery" },
      { tool: "toee_easyroutes_read", action: "get_delivery_status", inputSummary: "order 10422", outputSummary: "ETA today 3pm" },
    ],
  },
  {
    recordId: "ah_tool_outage",
    channel: "voice",
    identitySummary: "Verified: Summit Fleet",
    lastMessagePreview: "(call ended — case created)",
    lastActivityAt: NOW - 7 * HOUR,
    outcome: "escalated_to_case",
    toolSummary: "match_phone, get_ar_summary (failed)",
    toolFailure: true,
    timeline: [
      msg("ah_tool_outage", { messageId: "ahv_1", at: NOW - 7 * HOUR, channel: "voice", author: "customer", body: "What's my outstanding balance?", autoHandled: true }),
      msg("ah_tool_outage", { messageId: "ahv_2", at: NOW - 7 * HOUR + 30_000, channel: "voice", author: "hermes", body: "Our accounting system is temporarily unavailable; I've created a case for follow-up.", autoHandled: true }),
    ],
    toolCalls: [
      { tool: "toee_identity_lookup", action: "match_phone", inputSummary: "phone +1•••0098", outputSummary: "matched customer Summit Fleet" },
      { tool: "toee_qbo_read", action: "get_ar_summary", inputSummary: "customer Summit Fleet", outputSummary: "system unavailable", errorClass: "configuration_missing" },
    ],
  },
];

export function createSeed(): GatewayStoreSeed {
  // Deep copies so a singleton store mutated in dev never corrupts this module
  // constant (Slice 3's Postgres store will not share references at all).
  return structuredClone({ cases, threads, auditLog, autoHandled });
}
