// snake_case -> camelCase mappers + runtime validation for the per-profile API
// read model (ADR-0070/0141). The Postgres datastore returns JSON-safe snake_case
// rows with ISO-8601 timestamps (serialize_row); these functions map them onto
// the shared WorkbenchCase / AuditLogEntry shapes and reject contract violations
// (unknown channel/status, malformed timestamp, non-object payload) as governed
// HermesApiErrors so a bad upstream surfaces on the ADR-0090 banner instead of
// rendering garbage. Hand-written guards keep the BFF dependency-light.
import { HermesApiError } from "./hermes-api-client";
import type {
  AuditAction,
  AuditLogEntry,
  CaseChannel,
  CaseStatus,
  WorkbenchCase,
} from "./types";

const CHANNELS: readonly CaseChannel[] = ["sms", "email", "voice"];
const STATUSES: readonly CaseStatus[] = ["open", "in_progress", "resolved"];

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
