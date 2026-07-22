import { describe, expect, it } from "vitest";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import {
  handleGetAutoHandledViaApi,
  handleGetSalesOutreachViaApi,
  handleListAutoHandledViaApi,
  handleListSalesOutreachViaApi,
} from "./audit";

// 0.0.4 S09: the in-memory GatewayStore is gone. The store-seam assertions on
// ordering (most-recent-first), the sales_outreach-only filter, and the audit_view
// row a detail open writes are all datastore behavior now -- pinned by
// hermes-runtime/tests/test_datastore_audit_reads.py. What survives here is the
// BFF's own contract: the dispatched action and the snake_case -> wire mapping.


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
