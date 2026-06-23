import { describe, expect, it, beforeEach } from "vitest";
import { createDefaultMockDriver } from "@toee/domain-adapters";
import { createInMemoryGatewayStore } from "../../gateway/store";
import { createSeed } from "../../gateway/seed";
import type { GatewayStore } from "../../gateway/store";
import type { WorkbenchSession } from "../../auth/session";
import type { CopilotDeps } from "./deps";
import {
  handleGetAutoHandled,
  handleGetSalesOutreach,
  handleListAutoHandled,
  handleListSalesOutreach,
} from "./audit";

const NOW = 1_800_000_000_000;
const supervisor: WorkbenchSession = {
  accountId: "seed-supervisor",
  username: "supervisor",
  role: "workbench_supervisor",
  lastActivityAt: NOW,
};

let store: GatewayStore;
let deps: CopilotDeps;
beforeEach(() => {
  store = createInMemoryGatewayStore(createSeed());
  deps = { store, driver: createDefaultMockDriver(), session: supervisor, now: NOW };
});

describe("auto-handled audit", () => {
  it("lists auto-handled records (most recent first)", async () => {
    const res = handleListAutoHandled(deps);
    const body = (await res.json()) as { records: { recordId: string }[] };
    expect(body.records.map((r) => r.recordId)).toContain("ah_order_status");
    expect(body.records.map((r) => r.recordId)).toContain("ah_tool_outage");
  });

  it("returns a record detail and writes an audit_view entry", async () => {
    const appended: { action: string; recordId?: string }[] = [];
    const original = store.appendAuditEntry.bind(store);
    store.appendAuditEntry = (entry) => {
      appended.push(entry);
      original(entry);
    };

    const res = handleGetAutoHandled("ah_tool_outage", deps);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { record: { recordId: string; toolFailure: boolean } };
    expect(body.record.recordId).toBe("ah_tool_outage");
    expect(body.record.toolFailure).toBe(true);
    expect(
      appended.some((e) => e.action === "audit_view" && e.recordId === "ah_tool_outage"),
    ).toBe(true);
  });

  it("404s for an unknown auto-handled record", () => {
    expect(handleGetAutoHandled("nope", deps).status).toBe(404);
  });
});

describe("sales-outreach audit", () => {
  it("lists only sales_outreach cases", async () => {
    const res = handleListSalesOutreach(deps);
    const body = (await res.json()) as { cases: { caseId: string }[] };
    expect(body.cases.map((c) => c.caseId)).toEqual(["case_sales"]);
  });

  it("returns a sales-outreach case detail", async () => {
    const res = handleGetSalesOutreach("case_sales", deps);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { case: { caseId: string } };
    expect(body.case.caseId).toBe("case_sales");
  });

  it("404s for a non-sales case id", () => {
    expect(handleGetSalesOutreach("case_ar_urgent", deps).status).toBe(404);
  });
});
