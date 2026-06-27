import { describe, expect, it, beforeEach } from "vitest";
import { createDefaultMockDriver } from "@toee/domain-adapters";
import { createInMemoryGatewayStore } from "../../gateway/store";
import { createSeed } from "../../gateway/seed";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import type { GatewayStore } from "../../gateway/store";
import type { WorkbenchSession } from "../../auth/session";
import type { CopilotDeps } from "./deps";
import {
  handleGetAutoHandled,
  handleGetAutoHandledViaApi,
  handleGetSalesOutreach,
  handleGetSalesOutreachViaApi,
  handleListAutoHandled,
  handleListAutoHandledViaApi,
  handleListSalesOutreach,
  handleListSalesOutreachViaApi,
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

function apiClient(
  fetchImpl: (url: string, init: RequestInit) => Promise<Response>,
): HermesApiClient {
  return new HermesApiClient({
    baseUrl: "http://copilot.internal",
    token: "tok",
    actorAccountId: "seed-supervisor",
    fetchImpl,
  });
}

const autoHandledRow = {
  record_id: "ah_api",
  channel: "sms",
  identity_summary: "Verified: Lakeside Auto",
  last_message_preview: "Thanks!",
  last_activity_at: "2026-06-01T12:00:00+00:00",
  outcome: "auto_resolved",
  tool_summary: "match_phone",
  tool_failure: false,
  timeline: [],
  tool_calls: [],
};

const salesCaseRow = {
  id: "case_sales_api",
  case_id: "case_sales_api",
  channel: "sms",
  identity_summary: "",
  contact_reason: "sales_outreach",
  urgency: "low",
  urgent: false,
  status: "open",
  assignee_account_id: null,
  resolved_by_account_id: null,
  thread_id: "",
  last_message_preview: "SEO pitch",
  tool_failure: false,
  sms_session_active: false,
  opened_at: "2026-06-01T10:00:00+00:00",
  last_activity_at: "2026-06-01T12:00:00+00:00",
};

describe("handleListAutoHandledViaApi", () => {
  it("maps snake_case auto-handled rows", async () => {
    const res = await handleListAutoHandledViaApi(
      apiClient(async () =>
        new Response(
          JSON.stringify({ ok: true, data: { records: [autoHandledRow] } }),
          { status: 200 },
        ),
      ),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { records: { recordId: string }[] };
    expect(body.records[0]?.recordId).toBe("ah_api");
  });
});

describe("handleGetAutoHandledViaApi", () => {
  it("returns a mapped record", async () => {
    const res = await handleGetAutoHandledViaApi(
      apiClient(async () =>
        new Response(
          JSON.stringify({ ok: true, data: { record: autoHandledRow } }),
          { status: 200 },
        ),
      ),
      "ah_api",
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { record: { recordId: string } };
    expect(body.record.recordId).toBe("ah_api");
  });

  it("404s when the record is unknown", async () => {
    const res = await handleGetAutoHandledViaApi(
      apiClient(async () =>
        new Response(JSON.stringify({ ok: true, data: { record: null } }), {
          status: 200,
        }),
      ),
      "missing",
    );
    expect(res.status).toBe(404);
  });
});

describe("handleListSalesOutreachViaApi", () => {
  it("maps snake_case sales-outreach cases", async () => {
    const res = await handleListSalesOutreachViaApi(
      apiClient(async () =>
        new Response(
          JSON.stringify({ ok: true, data: { cases: [salesCaseRow] } }),
          { status: 200 },
        ),
      ),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { cases: { caseId: string; contactReason: string }[] };
    expect(body.cases[0]?.caseId).toBe("case_sales_api");
    expect(body.cases[0]?.contactReason).toBe("sales_outreach");
  });
});

describe("handleGetSalesOutreachViaApi", () => {
  it("returns a mapped case", async () => {
    const res = await handleGetSalesOutreachViaApi(
      apiClient(async () =>
        new Response(
          JSON.stringify({ ok: true, data: { case: salesCaseRow } }),
          { status: 200 },
        ),
      ),
      "case_sales_api",
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { case: { caseId: string } };
    expect(body.case.caseId).toBe("case_sales_api");
  });

  it("404s for a non-sales case", async () => {
    const res = await handleGetSalesOutreachViaApi(
      apiClient(async () =>
        new Response(JSON.stringify({ ok: true, data: { case: null } }), {
          status: 200,
        }),
      ),
      "case_ar_urgent",
    );
    expect(res.status).toBe(404);
  });
});
