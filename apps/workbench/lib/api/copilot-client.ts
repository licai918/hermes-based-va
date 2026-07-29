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
  CustomerPreferences,
  DraftRating,
  DraftRatingVerdict,
  InternalReviewReasonTag,
  MemoryPreferenceSlot,
  ThreadMessage,
  WorkbenchCase,
} from "../gateway/types";
import { PREFERENCE_SLOTS } from "../gateway/types";

const BASE = "/api/copilot";

export type ListCasesQuery = {
  statuses?: CaseStatus[];
  assignee?: AssigneeFilterMode;
};

export type DraftKind = "sms" | "email" | "note";

// toee_feedback.record_draft_outcome's implicit outcome (0.0.4 S09).
export type DraftOutcome = "sent_as_is" | "sent_edited";

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

// Customer Memory preferences (PAC-4/S17). The BFF passes case_id only -- the
// dispatch server resolves the customer binding server-side (S16) -- and never
// echoes a binding key back to the browser.
export function getPreferences(
  caseId: string,
): Promise<{ preferences: CustomerPreferences }> {
  return getJson(casePath(caseId, "preferences"));
}

export function upsertPreference(
  caseId: string,
  slot: MemoryPreferenceSlot,
  value: string,
): Promise<{ slot: MemoryPreferenceSlot; value: string; stored: boolean }> {
  return sendJson("POST", casePath(caseId, "preferences"), { slot, value });
}

export function clearPreference(
  caseId: string,
  slot: MemoryPreferenceSlot,
): Promise<{ slot: MemoryPreferenceSlot; cleared: boolean }> {
  return sendJson("POST", casePath(caseId, "preferences/clear"), { slot });
}

// One structured Customer Memory proposal (S14 FR-15, S15 FR-16). Mirrors the
// wire shape of AgentMemoryProposal (hermes-agent-client.ts) that the draft
// endpoint nests under `draft.proposals` -- see proposalsFromDraft below.
export type DraftProposal = {
  slot: MemoryPreferenceSlot;
  value: string;
  evidenceTurn?: string | null;
};

// Extracts the S14 proposals nested in a draft response's `data.proposals`
// (present only for a draft turn that called upsert_preference; absent for a
// store-path mock draft or a chat reply). Defensive against any other shape --
// an unrecognized entry is dropped rather than surfaced as a bogus proposal.
export function proposalsFromDraft(draftData: unknown): DraftProposal[] {
  if (!draftData || typeof draftData !== "object") return [];
  const raw = (draftData as { proposals?: unknown }).proposals;
  if (!Array.isArray(raw)) return [];
  const proposals: DraftProposal[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const { slot, value, evidence_turn } = entry as Record<string, unknown>;
    if (
      typeof slot !== "string" ||
      !(PREFERENCE_SLOTS as readonly string[]).includes(slot) ||
      typeof value !== "string"
    ) {
      continue;
    }
    proposals.push({
      slot: slot as MemoryPreferenceSlot,
      value,
      evidenceTurn: typeof evidence_turn === "string" ? evidence_turn : null,
    });
  }
  return proposals;
}

// Dismiss a pending proposal (S15, FR-16/FR-17): persists NO preference slot --
// a bad guess can't quietly land in memory (US17) -- only a governed audit
// record of the decision (slot/value/evidence, decider, timestamp).
export function dismissProposal(
  caseId: string,
  slot: MemoryPreferenceSlot,
  value: string,
  evidenceTurn?: string | null,
): Promise<{ slot: MemoryPreferenceSlot; dismissed: boolean }> {
  return sendJson("POST", casePath(caseId, "preferences/dismiss"), {
    slot,
    value,
    evidenceTurn: evidenceTurn ?? undefined,
  });
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

// A rep's thumbs up/down on one copilot draft (0.0.4 S06/S07, ADR-0154). Rides
// the draft correlation id minted client-side when the draft was produced
// (CopilotGateway.tsx) -- S09 will share that same id with the implicit
// send-outcome row for the same draft. `kind: "rating"` picks the explicit-
// rating branch of the feedback BFF route; S09 adds an "outcome" branch to
// this same route.
export function submitDraftFeedback(input: {
  caseId: string;
  draftCorrelationId: string;
  draftKind: DraftKind;
  draftText: string;
  verdict: DraftRatingVerdict;
  reasonTags?: InternalReviewReasonTag[];
  comment?: string;
}): Promise<{ rating: DraftRating }> {
  return sendJson<{ rating: DraftRating }>("POST", `${BASE}/feedback`, {
    kind: "rating",
    case_id: input.caseId,
    draft_correlation_id: input.draftCorrelationId,
    draft_kind: input.draftKind,
    draft_text: input.draftText,
    verdict: input.verdict,
    reason_tags: input.reasonTags ?? [],
    ...(input.comment ? { comment: input.comment } : {}),
  });
}

// The implicit sent_as_is/sent_edited capture (0.0.4 S09, FR-7/FR-9), fired
// fire-and-forget by GovernedSendModal after a successful governed send. Rides
// the SAME draft_correlation_id as submitDraftFeedback above so the two rows
// for one draft can be joined. `kind: "outcome"` picks this branch of the
// feedback BFF route.
export function recordDraftOutcome(input: {
  caseId: string;
  draftCorrelationId: string;
  draftKind: DraftKind;
  draftText: string;
  outcome: DraftOutcome;
  editDistanceRatio?: number;
  // 0.0.5 S27 (FR-33, D11): the text the rep actually sent -- edit-diff mining's
  // second operand. Optional, because the capture is fire-and-forget.
  sentText?: string;
}): Promise<unknown> {
  return sendJson("POST", `${BASE}/feedback`, {
    kind: "outcome",
    case_id: input.caseId,
    draft_correlation_id: input.draftCorrelationId,
    draft_kind: input.draftKind,
    draft_text: input.draftText,
    outcome: input.outcome,
    ...(input.editDistanceRatio !== undefined
      ? { edit_distance_ratio: input.editDistanceRatio }
      : {}),
    ...(input.sentText !== undefined ? { sent_text: input.sentText } : {}),
  });
}

export function sendSms(
  caseId: string,
  body: string,
  mediaUrl?: string,
): Promise<{ message: unknown }> {
  return sendJson("POST", `${BASE}/messages/sms/send`, {
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
