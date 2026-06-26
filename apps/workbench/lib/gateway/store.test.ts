import { beforeEach, describe, expect, it } from "vitest";
import { createInMemoryGatewayStore, type GatewayStore } from "./store";
import type {
  AutoHandledRecord,
  ThreadMessage,
  WorkbenchCase,
} from "./types";

const T = 1_760_000_000_000;

function makeCase(overrides: Partial<WorkbenchCase> & { caseId: string }): WorkbenchCase {
  return {
    channel: "sms",
    identitySummary: "Unmatched caller",
    contactReason: "order_status",
    urgent: false,
    status: "open",
    assigneeAccountId: null,
    resolvedByAccountId: null,
    threadId: `thread_${overrides.caseId}`,
    lastMessagePreview: "…",
    toolFailure: false,
    smsSessionActive: true,
    openedAt: T,
    lastActivityAt: T,
    ...overrides,
  };
}

function makeMessage(overrides: Partial<ThreadMessage> & { messageId: string; threadId: string }): ThreadMessage {
  return {
    at: T,
    author: "customer",
    channel: "sms",
    body: "hi",
    autoHandled: false,
    activeCaseSegment: true,
    ...overrides,
  };
}

// Queue fixture: urgent unassigned, normal unassigned (older), normal assigned,
// resolved, and a sales_outreach case (excluded from the queue per ADR-0050).
function seedCases(): WorkbenchCase[] {
  return [
    makeCase({ caseId: "c_normal_assigned", assigneeAccountId: "seed-rep", status: "in_progress", openedAt: T - 1000 }),
    makeCase({ caseId: "c_urgent_unassigned", urgent: true, openedAt: T - 500 }),
    makeCase({ caseId: "c_normal_unassigned_old", openedAt: T - 5000 }),
    makeCase({ caseId: "c_normal_unassigned_new", openedAt: T - 100 }),
    makeCase({ caseId: "c_resolved", status: "resolved", openedAt: T - 9000 }),
    makeCase({ caseId: "c_sales", contactReason: "sales_outreach", openedAt: T - 2000 }),
  ];
}

let store: GatewayStore;
beforeEach(() => {
  store = createInMemoryGatewayStore({ cases: seedCases() });
});

describe("listCases default queue", () => {
  it("excludes resolved and sales_outreach cases", () => {
    const ids = store.listCases({}).map((c) => c.caseId);
    expect(ids).not.toContain("c_resolved");
    expect(ids).not.toContain("c_sales");
  });

  it("sorts urgent first, then unassigned before assigned, then oldest first", () => {
    const ids = store.listCases({}).map((c) => c.caseId);
    expect(ids).toEqual([
      "c_urgent_unassigned",
      "c_normal_unassigned_old",
      "c_normal_unassigned_new",
      "c_normal_assigned",
    ]);
  });
});

describe("listCases filters", () => {
  it("mine returns only the caller's assigned cases", () => {
    const ids = store
      .listCases({ assignee: { mode: "mine", accountId: "seed-rep" } })
      .map((c) => c.caseId);
    expect(ids).toEqual(["c_normal_assigned"]);
  });

  it("mine_or_unassigned returns the caller's cases plus the unassigned pool", () => {
    const ids = store
      .listCases({ assignee: { mode: "mine_or_unassigned", accountId: "seed-rep" } })
      .map((c) => c.caseId);
    expect(ids).toContain("c_normal_assigned");
    expect(ids).toContain("c_urgent_unassigned");
    expect(ids).toContain("c_normal_unassigned_old");
  });

  it("status filter can surface resolved cases", () => {
    const ids = store.listCases({ statuses: ["resolved"] }).map((c) => c.caseId);
    expect(ids).toEqual(["c_resolved"]);
  });
});

describe("case management mutations", () => {
  it("claim assigns the case and moves it to in_progress", () => {
    const updated = store.claimCase("c_urgent_unassigned", "seed-rep");
    expect(updated?.assigneeAccountId).toBe("seed-rep");
    expect(updated?.status).toBe("in_progress");
  });

  it("assign sets the assignee without resolving", () => {
    const updated = store.assignCase("c_urgent_unassigned", "seed-supervisor");
    expect(updated?.assigneeAccountId).toBe("seed-supervisor");
    expect(updated?.status).not.toBe("resolved");
  });

  it("resolve records the resolving account", () => {
    const updated = store.resolveCase("c_normal_assigned", "seed-rep");
    expect(updated?.status).toBe("resolved");
    expect(updated?.resolvedByAccountId).toBe("seed-rep");
  });

  it("update priority toggles the urgent flag", () => {
    expect(store.updatePriority("c_normal_unassigned_old", true)?.urgent).toBe(true);
  });

  it("update contact reason sets the new reason", () => {
    expect(store.updateContactReason("c_urgent_unassigned", "billing")?.contactReason).toBe("billing");
  });

  it("returns undefined for an unknown case", () => {
    expect(store.claimCase("nope", "seed-rep")).toBeUndefined();
  });
});

describe("threads", () => {
  it("returns thread messages in chronological order", () => {
    store = createInMemoryGatewayStore({
      cases: seedCases(),
      threads: {
        thread_c_urgent_unassigned: [
          makeMessage({ messageId: "m2", threadId: "thread_c_urgent_unassigned", at: T }),
          makeMessage({ messageId: "m1", threadId: "thread_c_urgent_unassigned", at: T - 1000 }),
        ],
      },
    });
    const ids = store.getThread("c_urgent_unassigned").map((m) => m.messageId);
    expect(ids).toEqual(["m1", "m2"]);
  });

  it("appends a thread message and bumps last activity", () => {
    store.appendThreadMessage("c_urgent_unassigned", makeMessage({
      messageId: "out1",
      threadId: "thread_c_urgent_unassigned",
      author: "workbench",
      at: T + 10,
    }));
    expect(store.getThread("c_urgent_unassigned").map((m) => m.messageId)).toContain("out1");
    expect(store.getCase("c_urgent_unassigned")?.lastActivityAt).toBe(T + 10);
  });
});

describe("audit log", () => {
  it("records and reads back entries for a case", () => {
    store.appendAuditEntry({
      entryId: "a1",
      at: T,
      actorAccountId: "seed-rep",
      actorUsername: "rep",
      action: "case_view",
      caseId: "c_urgent_unassigned",
    });
    expect(store.getCaseAuditLog("c_urgent_unassigned").map((e) => e.entryId)).toEqual(["a1"]);
  });
});

describe("sales outreach and auto-handled audit", () => {
  it("lists only sales_outreach cases for the sales outreach audit", () => {
    expect(store.listSalesOutreach().map((c) => c.caseId)).toEqual(["c_sales"]);
  });

  it("lists auto-handled records most recent first", () => {
    const records: AutoHandledRecord[] = [
      { recordId: "ah_old", channel: "sms", identitySummary: "x", lastMessagePreview: "", lastActivityAt: T - 1000, outcome: "auto_resolved", toolSummary: "", toolFailure: false, timeline: [], toolCalls: [] },
      { recordId: "ah_new", channel: "email", identitySummary: "y", lastMessagePreview: "", lastActivityAt: T, outcome: "auto_resolved", toolSummary: "", toolFailure: true, timeline: [], toolCalls: [] },
    ];
    store = createInMemoryGatewayStore({ cases: [], autoHandled: records });
    expect(store.listAutoHandled().map((r) => r.recordId)).toEqual(["ah_new", "ah_old"]);
    expect(store.getAutoHandled("ah_new")?.toolFailure).toBe(true);
  });
});
