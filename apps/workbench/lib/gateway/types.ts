// Workbench Gateway domain types (ADR-0027 Copilot Gateway, ADR-0029 assignment +
// audit, ADR-0079 case queue, ADR-0082 thread context, ADR-0037 auto-handled,
// ADR-0085/0086 audit views). These back the in-memory GatewayStore that is the
// Slice-2 source of truth; Slice 3 swaps the store for Postgres without changing
// these shapes.
import type { MemoryPreferenceSlot } from "@toee/domain-adapters";

// Re-exported so the rest of the BFF/gateway layer imports the slot union from
// "./types" alongside everything else, without drifting from the domain-adapters
// driver's own slot names (ADR-0111).
export type { MemoryPreferenceSlot };

export type CaseChannel = "sms" | "email" | "voice";

export type CaseStatus = "open" | "in_progress" | "resolved";

// Human Intervention Case / Follow-up Case row. Fields cover the ADR-0079 queue
// columns plus the ADR-0082 sticky-header metadata. `contactReason` is a free
// string label (e.g. "order_status", "unknown", "sales_outreach", non-customer
// reasons) rather than a closed enum so launch playbooks can extend it.
export interface WorkbenchCase {
  caseId: string;
  channel: CaseChannel;
  identitySummary: string;
  contactReason: string;
  urgent: boolean;
  status: CaseStatus;
  assigneeAccountId: string | null;
  resolvedByAccountId: string | null;
  threadId: string;
  lastMessagePreview: string;
  toolFailure: boolean;
  // Governed Textline send (ADR-0083) is only enabled on SMS cases with an
  // active SMS Session on the current thread.
  smsSessionActive: boolean;
  openedAt: number;
  lastActivityAt: number;
}

export type ThreadAuthor = "customer" | "hermes" | "workbench";

// One read-only turn in a Case Thread Context timeline (ADR-0082). Prior
// Auto-Handled turns stay visible but de-emphasized (`autoHandled: true`); the
// active Human Intervention segment is highlighted (`activeCaseSegment: true`).
export interface ThreadMessage {
  messageId: string;
  threadId: string;
  at: number;
  author: ThreadAuthor;
  channel: CaseChannel;
  body: string;
  autoHandled: boolean;
  activeCaseSegment: boolean;
}

// Workbench Audit Log entry (ADR-0029). Records actor, timestamp, action, and the
// case or audit record it concerns. Written for login, case view, claim/assign,
// draft generation, status change, resolution, governed send, and audit views.
export type AuditAction =
  | "case_view"
  | "claim_case"
  | "assign_case"
  | "update_priority"
  | "update_contact_reason"
  | "resolve_case"
  | "draft_generated"
  | "textline_send"
  | "audit_view";

export interface AuditLogEntry {
  entryId: string;
  at: number;
  actorAccountId: string;
  actorUsername: string;
  action: AuditAction;
  caseId?: string;
  recordId?: string;
  detail?: string;
}

// One tool call captured for an Auto-Handled Interaction (ADR-0086 evidence
// panel): short input/output summaries plus an optional unavailable-system error
// class when the call failed.
export interface ToolCallEvidence {
  tool: string;
  action: string;
  inputSummary: string;
  outputSummary: string;
  errorClass?: string;
}

// Auto-Handled Interaction record (ADR-0037). Distinct from WorkbenchCase: these
// never enter the work queue; supervisors browse them read-only.
export interface AutoHandledRecord {
  recordId: string;
  channel: CaseChannel;
  identitySummary: string;
  lastMessagePreview: string;
  lastActivityAt: number;
  outcome: string;
  toolSummary: string;
  toolFailure: boolean;
  timeline: ThreadMessage[];
  toolCalls: ToolCallEvidence[];
}

// Assignee filter modes for the queue (ADR-0079). Reps default to
// `mine_or_unassigned`; supervisors/admins may widen to `all`.
export type AssigneeFilterMode = "all" | "mine" | "unassigned" | "mine_or_unassigned";

export interface CaseListFilter {
  // Defaults to ["open", "in_progress"] (resolved hidden) when omitted.
  statuses?: CaseStatus[];
  assignee?: { mode: AssigneeFilterMode; accountId?: string };
}

// Customer Memory preferences (ADR-0111/0114, PAC-4/S17). A case's four v1
// preference slots as read/corrected from the Workbench; any slot not yet set is
// simply absent rather than present with an empty value.
export const PREFERENCE_SLOTS: readonly MemoryPreferenceSlot[] = [
  "contact_time_preference",
  "channel_preference",
  "delivery_habit_note",
  "communication_style_note",
];

export type CustomerPreferences = Partial<Record<MemoryPreferenceSlot, string>>;
