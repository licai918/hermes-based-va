// Mock driver fragment for `toee_case` (ADR-0064). The External Customer Service
// Profile opens Follow-up Cases (`create_case`) and adjusts urgency / contact
// reason on an open case (`update_case`). Output is fully deterministic — the
// caseId is derived from the request params, never random — so Launch Eval can
// assert that a case was created without network access.
//
// ADR deviation: the issue prompt named the urgency field `priority`. ADR-0064
// defines the allowed field as `urgency`, so this module uses `urgency`.
import type { MockHandlerRegistry } from "./mock-driver";

export interface CaseMockData {
  // Prefix for the deterministic caseId, e.g. "case" -> "case_1a2b3c4d".
  caseIdPrefix: string;
  // Cases opened by the external profile are always "open" on creation.
  defaultStatus: "open";
  // Optional default urgency from non-customer playbooks (e.g. government
  // traffic marked Urgent Follow-up Case) when the caller supplies none.
  defaultUrgency?: string;
}

export const caseBaselineData: CaseMockData = {
  caseIdPrefix: "case",
  defaultStatus: "open",
};

export interface CaseRecord {
  caseId: string;
  status: "open";
  contactReason?: string;
  urgency?: string;
  summary?: string;
  channelThreadId?: string;
}

function readString(
  params: Record<string, unknown>,
  ...keys: string[]
): string | undefined {
  for (const key of keys) {
    const value = params[key];
    if (typeof value === "string" && value.length > 0) {
      return value;
    }
  }
  return undefined;
}

// Deterministic 32-bit FNV-1a hash rendered as an 8-char hex suffix. Stable for
// identical inputs and distinct for different inputs; no randomness or clock.
function deterministicId(
  prefix: string,
  parts: Array<string | undefined>,
): string {
  const input = parts.map((part) => part ?? "").join("|");
  let hash = 0x811c9dc5;
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return `${prefix}_${(hash >>> 0).toString(16).padStart(8, "0")}`;
}

function createCase(
  data: CaseMockData,
  params: Record<string, unknown>,
): CaseRecord {
  const contactReason = readString(params, "contactReason", "contact_reason");
  const summary = readString(params, "summary");
  const channelThreadId = readString(
    params,
    "channelThreadId",
    "channel_thread_id",
  );
  const urgency = readString(params, "urgency") ?? data.defaultUrgency;

  const record: CaseRecord = {
    caseId: deterministicId(data.caseIdPrefix, [
      contactReason,
      summary,
      channelThreadId,
    ]),
    status: data.defaultStatus,
  };
  if (contactReason !== undefined) {
    record.contactReason = contactReason;
  }
  if (urgency !== undefined) {
    record.urgency = urgency;
  }
  if (summary !== undefined) {
    record.summary = summary;
  }
  if (channelThreadId !== undefined) {
    record.channelThreadId = channelThreadId;
  }
  return record;
}

function updateCase(
  data: CaseMockData,
  params: Record<string, unknown>,
): CaseRecord {
  const contactReason = readString(params, "contactReason", "contact_reason");
  const urgency = readString(params, "urgency");
  const caseId =
    readString(params, "caseId", "case_id") ??
    deterministicId(data.caseIdPrefix, [contactReason, urgency]);

  const record: CaseRecord = { caseId, status: data.defaultStatus };
  // update_case only adjusts urgency and contact_reason per ADR-0064.
  if (contactReason !== undefined) {
    record.contactReason = contactReason;
  }
  if (urgency !== undefined) {
    record.urgency = urgency;
  }
  return record;
}

export function createCaseMockHandlers(
  data: CaseMockData = caseBaselineData,
): MockHandlerRegistry {
  return {
    toee_case: {
      create_case: (params) => createCase(data, params),
      update_case: (params) => updateCase(data, params),
    },
  };
}

export const caseMockHandlers: MockHandlerRegistry = createCaseMockHandlers();
