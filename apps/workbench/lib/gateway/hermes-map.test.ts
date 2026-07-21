import { describe, expect, it } from "vitest";
import { HermesApiError } from "./hermes-api-client";
import {
  mapAuditEntry,
  mapAutoHandledRecord,
  mapMemoryAuditEntry,
  mapPreferences,
  mapThreadMessage,
  mapWorkbenchCase,
} from "./hermes-map";

const fullCaseRow = {
  id: "case_1",
  case_id: "case_1",
  channel: "sms",
  identity_summary: "Verified: cust_900",
  contact_reason: "order_status",
  urgency: "high",
  urgent: true,
  status: "open",
  assignee_account_id: null,
  resolved_by_account_id: null,
  customer_thread_id: "thr_1",
  thread_id: "thr_1",
  last_message_preview: "the latest reply",
  tool_failure: false,
  sms_session_active: true,
  opened_at: "2026-06-01T12:00:00+00:00",
  last_activity_at: "2026-06-01T13:00:00+00:00",
};

describe("mapWorkbenchCase", () => {
  it("maps a snake_case datastore row onto the camelCase WorkbenchCase", () => {
    const c = mapWorkbenchCase(fullCaseRow);
    expect(c.caseId).toBe("case_1");
    expect(c.channel).toBe("sms");
    expect(c.identitySummary).toBe("Verified: cust_900");
    expect(c.contactReason).toBe("order_status");
    expect(c.urgent).toBe(true);
    expect(c.assigneeAccountId).toBeNull();
    expect(c.threadId).toBe("thr_1");
    expect(c.lastMessagePreview).toBe("the latest reply");
    expect(c.toolFailure).toBe(false);
    expect(c.smsSessionActive).toBe(true);
    expect(c.openedAt).toBe(Date.parse("2026-06-01T12:00:00+00:00"));
    expect(c.lastActivityAt).toBe(Date.parse("2026-06-01T13:00:00+00:00"));
  });

  it("keeps a present assignee account id", () => {
    const c = mapWorkbenchCase({ ...fullCaseRow, assignee_account_id: "acct_7" });
    expect(c.assigneeAccountId).toBe("acct_7");
  });

  it("rejects an unknown channel as a contract violation (ADR-0070)", () => {
    expect(() =>
      mapWorkbenchCase({ ...fullCaseRow, channel: "carrier_pigeon" }),
    ).toThrow(HermesApiError);
  });

  it("rejects an unknown status", () => {
    expect(() => mapWorkbenchCase({ ...fullCaseRow, status: "archived" })).toThrow(
      HermesApiError,
    );
  });

  it("rejects a malformed timestamp", () => {
    expect(() =>
      mapWorkbenchCase({ ...fullCaseRow, opened_at: "not-a-date" }),
    ).toThrow(HermesApiError);
  });

  it("rejects a non-object payload", () => {
    expect(() => mapWorkbenchCase(null)).toThrow(HermesApiError);
  });
});

describe("mapAuditEntry", () => {
  const auditRow = {
    id: "audit_1",
    account_id: "acct_jane",
    actor_username: "jane",
    profile: "internal_copilot",
    action: "claim_case",
    target_type: "case",
    target_id: "case_1",
    details: { assignee_account_id: "acct_jane" },
    created_at: "2026-06-01T12:00:00+00:00",
  };

  it("maps a snake_case audit row onto the camelCase AuditLogEntry", () => {
    const e = mapAuditEntry(auditRow);
    expect(e.entryId).toBe("audit_1");
    expect(e.actorAccountId).toBe("acct_jane");
    expect(e.actorUsername).toBe("jane");
    expect(e.action).toBe("claim_case");
    expect(e.caseId).toBe("case_1");
    expect(e.at).toBe(Date.parse("2026-06-01T12:00:00+00:00"));
  });

  it("defaults a missing actor_username to empty (unknown account)", () => {
    const e = mapAuditEntry({ ...auditRow, actor_username: null });
    expect(e.actorUsername).toBe("");
  });

  it("omits caseId when the audit target is not a case", () => {
    const e = mapAuditEntry({ ...auditRow, target_type: "account", target_id: "acct_1" });
    expect(e.caseId).toBeUndefined();
  });
});

describe("mapThreadMessage", () => {
  const messageRow = {
    id: "mt_1",
    customer_thread_id: "thr_1",
    author: "hermes",
    channel: "sms",
    body: "active human reply",
    auto_handled: false,
    active_case_segment: true,
    created_at: "2026-06-01T12:00:00+00:00",
  };

  it("maps a snake_case message turn onto the camelCase ThreadMessage", () => {
    const m = mapThreadMessage(messageRow);
    expect(m.messageId).toBe("mt_1");
    expect(m.threadId).toBe("thr_1");
    expect(m.author).toBe("hermes");
    expect(m.channel).toBe("sms");
    expect(m.body).toBe("active human reply");
    expect(m.autoHandled).toBe(false);
    expect(m.activeCaseSegment).toBe(true);
    expect(m.at).toBe(Date.parse("2026-06-01T12:00:00+00:00"));
  });

  it("carries an auto-handled, de-emphasized turn", () => {
    const m = mapThreadMessage({
      ...messageRow,
      auto_handled: true,
      active_case_segment: false,
    });
    expect(m.autoHandled).toBe(true);
    expect(m.activeCaseSegment).toBe(false);
  });

  it("rejects an unknown author as a contract violation (ADR-0070)", () => {
    expect(() => mapThreadMessage({ ...messageRow, author: "robot" })).toThrow(
      HermesApiError,
    );
  });

  it("rejects an unknown channel", () => {
    expect(() =>
      mapThreadMessage({ ...messageRow, channel: "carrier_pigeon" }),
    ).toThrow(HermesApiError);
  });

  it("rejects a malformed timestamp", () => {
    expect(() =>
      mapThreadMessage({ ...messageRow, created_at: "not-a-date" }),
    ).toThrow(HermesApiError);
  });
});

describe("mapPreferences", () => {
  it("whitelists the four v1 slots (ADR-0111) and drops everything else", () => {
    const p = mapPreferences({
      binding_key: "cust_900",
      contact_time_preference: "evenings",
      channel_preference: "sms",
      delivery_habit_note: "leave at side door",
      communication_style_note: "prefers brief replies",
      some_future_field: "should never surface",
    });
    expect(p).toEqual({
      contact_time_preference: "evenings",
      channel_preference: "sms",
      delivery_habit_note: "leave at side door",
      communication_style_note: "prefers brief replies",
    });
    expect(p).not.toHaveProperty("binding_key");
    expect(p).not.toHaveProperty("some_future_field");
  });

  it("omits an absent slot rather than filling it with a default", () => {
    const p = mapPreferences({ contact_time_preference: "evenings" });
    expect(p).toEqual({ contact_time_preference: "evenings" });
    expect(p).not.toHaveProperty("channel_preference");
  });

  it("maps an empty preference object to an empty result", () => {
    expect(mapPreferences({})).toEqual({});
  });

  it("rejects a non-object payload as a contract violation (ADR-0070)", () => {
    expect(() => mapPreferences(null)).toThrow(HermesApiError);
  });
});

describe("mapAutoHandledRecord", () => {
  it("maps a snake_case auto-handled record", () => {
    const record = mapAutoHandledRecord({
      record_id: "ah_1",
      channel: "sms",
      identity_summary: "Verified: cust",
      last_message_preview: "Thanks",
      last_activity_at: "2026-06-01T12:00:00+00:00",
      outcome: "auto_resolved",
      tool_summary: "match_phone",
      tool_failure: false,
      timeline: [],
      tool_calls: [],
    });
    expect(record.recordId).toBe("ah_1");
    expect(record.channel).toBe("sms");
    expect(record.toolFailure).toBe(false);
    expect(record.lastActivityAt).toBe(Date.parse("2026-06-01T12:00:00+00:00"));
  });
});

// S16 (FR-17): the proposal-history section needs a dismissed proposal's
// proposed value, not just its slot -- lifted from details.value the same
// way `slot` is already lifted from details.slot.
describe("mapMemoryAuditEntry", () => {
  it("lifts details.value onto the entry for a proposal_dismissed row", () => {
    const entry = mapMemoryAuditEntry({
      id: "audit_1",
      account_id: "acct_rep_1",
      actor_username: "rep_1",
      action: "proposal_dismissed",
      target_id: "channel_preference",
      details: { slot: "channel_preference", value: "sms", evidence: "text me" },
      created_at: "2026-07-01T09:00:00Z",
    });
    expect(entry.action).toBe("proposal_dismissed");
    expect(entry.slot).toBe("channel_preference");
    expect(entry.value).toBe("sms");
    expect(entry.actorUsername).toBe("rep_1");
    expect(entry.actorAccountId).toBe("acct_rep_1");
    expect(entry.at).toBe(Date.parse("2026-07-01T09:00:00Z"));
  });

  it("leaves value undefined when details carries none (e.g. preference_cleared)", () => {
    const entry = mapMemoryAuditEntry({
      id: "audit_2",
      account_id: "acct_sup_1",
      action: "preference_cleared",
      target_id: "channel_preference",
      details: { slot: "channel_preference", binding_key: "cust_900" },
      created_at: "2026-07-04T09:00:00Z",
    });
    expect(entry.value).toBeUndefined();
  });
});
