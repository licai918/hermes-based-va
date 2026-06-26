import { describe, expect, it } from "vitest";
import { HermesApiError } from "./hermes-api-client";
import { mapAuditEntry, mapThreadMessage, mapWorkbenchCase } from "./hermes-map";

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
