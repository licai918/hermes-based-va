// snake_case -> camelCase mappers + runtime validation for the per-profile API
// read model (ADR-0070/0141). The Postgres datastore returns JSON-safe snake_case
// rows with ISO-8601 timestamps (serialize_row); these functions map them onto
// the shared WorkbenchCase / AuditLogEntry shapes and reject contract violations
// (unknown channel/status, malformed timestamp, non-object payload) as governed
// HermesApiErrors so a bad upstream surfaces on the ADR-0090 banner instead of
// rendering garbage. Hand-written guards keep the BFF dependency-light.
import { HermesApiError } from "./hermes-api-client";
import {
  PREFERENCE_SLOTS,
  type AuditAction,
  type AuditLogEntry,
  type AutoHandledRecord,
  type CaseChannel,
  type CaseStatus,
  type CustomerPreferences,
  type MemoryAuditEntry,
  type MemoryAuditView,
  type MemoryPreferenceSlot,
  type MemorySlotAttribution,
  type MemoryWriteSource,
  type ThreadAuthor,
  type ThreadMessage,
  type ToolCallEvidence,
  type WorkbenchCase,
} from "./types";

const CHANNELS: readonly CaseChannel[] = ["sms", "email", "voice"];
const STATUSES: readonly CaseStatus[] = ["open", "in_progress", "resolved"];
const AUTHORS: readonly ThreadAuthor[] = ["customer", "hermes", "workbench"];

function asObject(raw: unknown, label: string): Record<string, unknown> {
  if (typeof raw !== "object" || raw === null) {
    throw new HermesApiError("unexpected_error", `malformed ${label} payload`);
  }
  return raw as Record<string, unknown>;
}

function optionalString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function requiredString(value: unknown, label: string): string {
  if (typeof value === "string" && value.length > 0) return value;
  throw new HermesApiError("unexpected_error", `missing ${label}`);
}

function nullableString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function isoToMs(value: unknown, label: string): number {
  if (typeof value === "number") return value;
  if (typeof value === "string") {
    const ms = Date.parse(value);
    if (!Number.isNaN(ms)) return ms;
  }
  throw new HermesApiError("unexpected_error", `malformed ${label} timestamp`);
}

// The datastore stores audit details as a JSONB object; the WorkbenchCase audit
// view shows an optional free-text detail. Render a non-empty object compactly.
function optionalDetail(value: unknown): string | undefined {
  if (typeof value === "string" && value.length > 0) return value;
  if (value && typeof value === "object" && Object.keys(value).length > 0) {
    return JSON.stringify(value);
  }
  return undefined;
}

export function mapWorkbenchCase(raw: unknown): WorkbenchCase {
  const r = asObject(raw, "case");
  const channel = r.channel;
  const status = r.status;
  if (!(CHANNELS as readonly unknown[]).includes(channel)) {
    throw new HermesApiError("unexpected_error", `unknown case channel: ${String(channel)}`);
  }
  if (!(STATUSES as readonly unknown[]).includes(status)) {
    throw new HermesApiError("unexpected_error", `unknown case status: ${String(status)}`);
  }
  return {
    caseId: requiredString(r.case_id, "case_id"),
    channel: channel as CaseChannel,
    identitySummary: optionalString(r.identity_summary),
    contactReason: optionalString(r.contact_reason),
    urgent: r.urgent === true,
    status: status as CaseStatus,
    assigneeAccountId: nullableString(r.assignee_account_id),
    resolvedByAccountId: nullableString(r.resolved_by_account_id),
    threadId: optionalString(r.thread_id),
    lastMessagePreview: optionalString(r.last_message_preview),
    toolFailure: r.tool_failure === true,
    smsSessionActive: r.sms_session_active === true,
    openedAt: isoToMs(r.opened_at, "opened_at"),
    lastActivityAt: isoToMs(r.last_activity_at, "last_activity_at"),
  };
}

// Maps a snake_case message_turn row onto the camelCase ThreadMessage (ADR-0082
// Case Thread Context timeline). channel + active_case_segment are computed by
// the datastore (a thread is single-channel; the active segment is the
// non-auto-handled turns); an unknown author/channel is a contract violation.
export function mapThreadMessage(raw: unknown): ThreadMessage {
  const r = asObject(raw, "thread message");
  const author = r.author;
  const channel = r.channel;
  if (!(AUTHORS as readonly unknown[]).includes(author)) {
    throw new HermesApiError(
      "unexpected_error",
      `unknown thread author: ${String(author)}`,
    );
  }
  if (!(CHANNELS as readonly unknown[]).includes(channel)) {
    throw new HermesApiError(
      "unexpected_error",
      `unknown thread channel: ${String(channel)}`,
    );
  }
  return {
    messageId: requiredString(r.id, "message id"),
    threadId: optionalString(r.customer_thread_id),
    at: isoToMs(r.created_at, "created_at"),
    author: author as ThreadAuthor,
    channel: channel as CaseChannel,
    body: optionalString(r.body),
    autoHandled: r.auto_handled === true,
    activeCaseSegment: r.active_case_segment === true,
  };
}

export function mapAuditEntry(raw: unknown): AuditLogEntry {
  const r = asObject(raw, "audit entry");
  const entry: AuditLogEntry = {
    entryId: requiredString(r.id, "audit id"),
    at: isoToMs(r.created_at, "created_at"),
    actorAccountId: optionalString(r.account_id),
    actorUsername: optionalString(r.actor_username),
    action: optionalString(r.action) as AuditAction,
  };
  if (r.target_type === "case") {
    const caseId = nullableString(r.target_id);
    if (caseId) entry.caseId = caseId;
  }
  const detail = optionalDetail(r.details);
  if (detail) entry.detail = detail;
  return entry;
}

export function mapToolCallEvidence(raw: unknown): ToolCallEvidence {
  const r = asObject(raw, "tool call evidence");
  const evidence: ToolCallEvidence = {
    tool: optionalString(r.tool),
    action: optionalString(r.action),
    inputSummary: optionalString(r.input_summary ?? r.inputSummary),
    outputSummary: optionalString(r.output_summary ?? r.outputSummary),
  };
  const errorClass = nullableString(r.error_class ?? r.errorClass);
  if (errorClass) evidence.errorClass = errorClass;
  return evidence;
}

// Whitelists the four v1 Customer Memory slots (ADR-0111) out of the raw
// dispatch preference map. Deliberately a whitelist copy, not a validate-all: an
// unrecognised key (e.g. a future slot, or `binding_key` if a caller forgot to
// strip it) is silently dropped rather than rejected, since the whole point is
// that only these four names ever cross the BFF boundary to the browser.
export function mapPreferences(raw: unknown): CustomerPreferences {
  const r = asObject(raw, "preferences");
  const result: CustomerPreferences = {};
  for (const slot of PREFERENCE_SLOTS) {
    const value = r[slot];
    if (typeof value === "string") result[slot] = value;
  }
  return result;
}

const MEMORY_WRITE_SOURCES: readonly MemoryWriteSource[] = [
  "customer_explicit",
  "employee_confirmed",
  "copilot_agent",
  "merged_provisional",
];

function nullableSource(value: unknown): MemoryWriteSource | null {
  return (MEMORY_WRITE_SOURCES as readonly unknown[]).includes(value)
    ? (value as MemoryWriteSource)
    : null;
}

// Supervisor Memory Audit View (0.0.3 S20, FR-20). ``binding_key`` on the raw
// dispatch payload is deliberately never read here -- same rule mapPreferences
// follows -- so it can't accidentally leak into the mapped view a route returns
// to the browser.
export function mapMemorySlotAttribution(raw: unknown): MemorySlotAttribution {
  const r = asObject(raw, "memory slot");
  const slot = r.slot_name;
  if (!(PREFERENCE_SLOTS as readonly unknown[]).includes(slot)) {
    throw new HermesApiError("unexpected_error", `unknown memory slot: ${String(slot)}`);
  }
  return {
    slot: slot as MemoryPreferenceSlot,
    value: requiredString(r.slot_value, "slot_value"),
    source: nullableSource(r.source),
    actorAccountId: nullableString(r.actor_account_id),
    evidence: nullableString(r.evidence),
    createdAt: isoToMs(r.created_at, "created_at"),
    updatedAt: isoToMs(r.updated_at, "updated_at"),
  };
}

// Not a closed enum (unlike mapAuditEntry's case AuditAction): S16 joins
// accepted-proposal rows into this history later, so an action this mapper
// doesn't yet know about is passed through rather than rejected -- the S16
// boundary this slice must not enforce.
export function mapMemoryAuditEntry(raw: unknown): MemoryAuditEntry {
  const r = asObject(raw, "memory audit entry");
  const details = r.details;
  const detailsObj =
    details && typeof details === "object" ? (details as Record<string, unknown>) : null;
  const slot =
    detailsObj && typeof detailsObj.slot === "string" ? detailsObj.slot : nullableString(r.target_id);
  const entry: MemoryAuditEntry = {
    entryId: requiredString(r.id, "audit id"),
    at: isoToMs(r.created_at, "created_at"),
    actorAccountId: nullableString(r.account_id),
    actorUsername: nullableString(r.actor_username),
    action: optionalString(r.action),
    slot,
  };
  // S16 (FR-17): a proposal_dismissed row's proposed value, pulled from
  // details.value the same way slot is pulled from details.slot above -- the
  // proposal-history section needs it to show what was proposed, not just
  // that a slot was dismissed.
  if (detailsObj && typeof detailsObj.value === "string") entry.value = detailsObj.value;
  const detail = optionalDetail(details);
  if (detail) entry.detail = detail;
  return entry;
}

export function mapMemoryAuditView(raw: unknown): MemoryAuditView {
  const r = asObject(raw, "memory audit view");
  const slotsRaw = Array.isArray(r.slots) ? r.slots : [];
  const historyRaw = Array.isArray(r.audit) ? r.audit : [];
  return {
    slots: slotsRaw.map(mapMemorySlotAttribution),
    history: historyRaw.map(mapMemoryAuditEntry),
  };
}

export function mapAutoHandledRecord(raw: unknown): AutoHandledRecord {
  const r = asObject(raw, "auto-handled record");
  const channel = r.channel;
  if (!(CHANNELS as readonly unknown[]).includes(channel)) {
    throw new HermesApiError(
      "unexpected_error",
      `unknown auto-handled channel: ${String(channel)}`,
    );
  }
  const timelineRaw = Array.isArray(r.timeline) ? r.timeline : [];
  const toolCallsField = r.tool_calls ?? r.toolCalls;
  const toolCallsRaw = Array.isArray(toolCallsField) ? toolCallsField : [];
  return {
    recordId: requiredString(r.record_id ?? r.recordId, "record_id"),
    channel: channel as CaseChannel,
    identitySummary: optionalString(r.identity_summary ?? r.identitySummary),
    lastMessagePreview: optionalString(
      r.last_message_preview ?? r.lastMessagePreview,
    ),
    lastActivityAt: isoToMs(
      r.last_activity_at ?? r.lastActivityAt,
      "last_activity_at",
    ),
    outcome: optionalString(r.outcome),
    toolSummary: optionalString(r.tool_summary ?? r.toolSummary),
    toolFailure: r.tool_failure === true || r.toolFailure === true,
    timeline: timelineRaw.map(mapThreadMessage),
    toolCalls: toolCallsRaw.map(mapToolCallEvidence),
  };
}
