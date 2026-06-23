// Typed, thin wrappers over the same-origin Copilot BFF (ADR-0094). Each call
// delegates to the shared http helpers so non-2xx responses raise the typed
// ApiError that the UI surfaces through the global error banner. These are the
// only network calls the Copilot Workbench UI makes; the HttpOnly session cookie
// rides along automatically.
import { getJson, sendJson } from "./http";
import type {
  AssigneeFilterMode,
  AuditLogEntry,
  CaseStatus,
  ThreadMessage,
  WorkbenchCase,
} from "../gateway/types";

const BASE = "/api/copilot";

export type ListCasesQuery = {
  statuses?: CaseStatus[];
  assignee?: AssigneeFilterMode;
};

export type DraftKind = "sms" | "email" | "note";

export type ChatResponse = {
  state: "needs_case" | "ready";
  reply: string;
  draftCard?: { channel: "sms"; body: string };
};

function casePath(caseId: string, suffix: string): string {
  return `${BASE}/cases/${encodeURIComponent(caseId)}/${suffix}`;
}

// GET the queue. Statuses are repeated `status=` params and the assignee mode is
// a single `assignee=` param, matching the BFF parser; an empty filter sends no
// query string so the BFF applies its role-aware defaults.
export function listCases(
  query: ListCasesQuery = {},
): Promise<{ cases: WorkbenchCase[] }> {
  const params = new URLSearchParams();
  for (const status of query.statuses ?? []) params.append("status", status);
  if (query.assignee) params.set("assignee", query.assignee);
  const qs = params.toString();
  return getJson(`${BASE}/cases${qs ? `?${qs}` : ""}`);
}

export function getThread(
  caseId: string,
): Promise<{ case: WorkbenchCase; messages: ThreadMessage[] }> {
  return getJson(casePath(caseId, "thread"));
}

export function getCaseAuditLog(
  caseId: string,
): Promise<{ entries: AuditLogEntry[] }> {
  return getJson(casePath(caseId, "audit-log"));
}

export function claimCase(caseId: string): Promise<{ case: WorkbenchCase }> {
  return sendJson("POST", casePath(caseId, "claim"));
}

export function assignCase(
  caseId: string,
  assigneeAccountId: string,
): Promise<{ case: WorkbenchCase }> {
  return sendJson("POST", casePath(caseId, "assign"), { assigneeAccountId });
}

export function resolveCase(caseId: string): Promise<{ case: WorkbenchCase }> {
  return sendJson("POST", casePath(caseId, "resolve"));
}

export function setPriority(
  caseId: string,
  urgent: boolean,
): Promise<{ case: WorkbenchCase }> {
  return sendJson("POST", casePath(caseId, "priority"), { urgent });
}

export function setContactReason(
  caseId: string,
  contactReason: string,
): Promise<{ case: WorkbenchCase }> {
  return sendJson("POST", casePath(caseId, "contact-reason"), { contactReason });
}

export function draft(
  kind: DraftKind,
  caseId: string,
  prompt?: string,
): Promise<{ draft: unknown }> {
  return sendJson("POST", `${BASE}/drafts/${kind}`, { caseId, prompt });
}

export function chat(message: string, caseId?: string): Promise<ChatResponse> {
  return sendJson("POST", `${BASE}/chat`, { caseId, message });
}

export function sendTextline(
  caseId: string,
  body: string,
  mediaUrl?: string,
): Promise<{ message: unknown }> {
  return sendJson("POST", `${BASE}/messages/textline/send`, {
    caseId,
    body,
    mediaUrl,
  });
}

// Drafts come back driver-shaped (string or object). Normalize defensively to a
// single editable string for the draft card without throwing on odd shapes.
export function normalizeDraft(draftData: unknown): string {
  if (typeof draftData === "string") return draftData;
  if (draftData && typeof draftData === "object") {
    const record = draftData as { draft?: unknown; body?: unknown };
    if (typeof record.draft === "string") return record.draft;
    if (typeof record.body === "string") return record.body;
  }
  return JSON.stringify(draftData);
}
