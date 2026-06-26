import { describe, expect, it } from "vitest";
import { createInMemoryGatewayStore } from "./store";
import { createSeed } from "./seed";

describe("gateway seed", () => {
  it("produces an open queue that excludes resolved and sales_outreach", () => {
    const store = createInMemoryGatewayStore(createSeed());
    const ids = store.listCases({}).map((c) => c.caseId);
    expect(ids).toContain("case_ar_urgent");
    expect(ids).not.toContain("case_resolved");
    expect(ids).not.toContain("case_sales");
    // ADR-0079: an urgent case sorts to the top.
    expect(store.listCases({})[0]?.urgent).toBe(true);
  });

  it("includes a governed-send-eligible SMS case (ADR-0083 preconditions)", () => {
    const store = createInMemoryGatewayStore(createSeed());
    const ar = store.getCase("case_ar_urgent");
    expect(ar?.channel).toBe("sms");
    expect(ar?.smsSessionActive).toBe(true);
    expect(ar?.status).not.toBe("resolved");
    expect(store.getThread("case_ar_urgent").length).toBeGreaterThan(0);
  });

  it("surfaces sales-outreach and a tool-failure auto-handled record", () => {
    const store = createInMemoryGatewayStore(createSeed());
    expect(store.listSalesOutreach().map((c) => c.caseId)).toEqual(["case_sales"]);
    const outage = store.getAutoHandled("ah_tool_outage");
    expect(outage?.toolFailure).toBe(true);
    expect(outage?.toolCalls.some((t) => t.errorClass)).toBe(true);
  });

  it("gives each store an independent copy of the seed", () => {
    const a = createInMemoryGatewayStore(createSeed());
    const b = createInMemoryGatewayStore(createSeed());
    a.claimCase("case_ar_urgent", "seed-rep");
    expect(b.getCase("case_ar_urgent")?.assigneeAccountId).toBeNull();
  });
});
