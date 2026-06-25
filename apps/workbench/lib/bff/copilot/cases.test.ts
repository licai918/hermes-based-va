import { beforeEach, describe, expect, it } from "vitest";
import { createDefaultMockDriver, type ToolDriver } from "@toee/domain-adapters";
import { WORKBENCH_ROLES, type WorkbenchRoleId } from "@toee/shared";
import type { WorkbenchSession } from "../../auth/session";
import { createInMemoryGatewayStore, type GatewayStore } from "../../gateway/store";
import { createSeed } from "../../gateway/seed";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import type { AuditAction, WorkbenchCase } from "../../gateway/types";
import type { CopilotDeps } from "./deps";
import {
  handleAssign,
  handleClaim,
  handleContactReason,
  handleGetAuditLog,
  handleGetAuditLogViaApi,
  handleGetCase,
  handleGetCaseViaApi,
  handleGetThread,
  handleGetThreadViaApi,
  handleListCases,
  handleListCasesViaApi,
  handlePriority,
  handleResolve,
} from "./cases";

const NOW = 1_700_000_000_000;

let store: GatewayStore;
let driver: ToolDriver;

beforeEach(() => {
  store = createInMemoryGatewayStore(createSeed());
  driver = createDefaultMockDriver();
});

function session(
  role: WorkbenchRoleId = WORKBENCH_ROLES.rep,
  accountId = "seed-rep",
  username = "rep",
): WorkbenchSession {
  return { accountId, username, role, lastActivityAt: NOW };
}

function deps(s: WorkbenchSession = session()): CopilotDeps {
  return { store, driver, session: s, now: NOW };
}

function listReq(query = ""): Request {
  return new Request(`http://localhost/api/copilot/cases${query}`);
}

function jsonReq(body: unknown): Request {
  return new Request("http://localhost/api/copilot/cases/x", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function actions(caseId: string): AuditAction[] {
  return store.getCaseAuditLog(caseId).map((e) => e.action);
}

// A realistic snake_case datastore read-model row (ADR-0064/0141) for the
// per-profile API path: the BFF maps + validates it onto a WorkbenchCase.
const apiCaseRow = {
  id: "case_api",
  case_id: "case_api",
  channel: "sms",
  identity_summary: "Verified: cust_900",
  contact_reason: "order_status",
  urgency: "high",
  urgent: true,
  status: "open",
  assignee_account_id: null,
  resolved_by_account_id: null,
  customer_thread_id: "thr_api",
  thread_id: "thr_api",
  last_message_preview: "hi",
  tool_failure: false,
  sms_session_active: true,
  opened_at: "2026-06-01T12:00:00+00:00",
  last_activity_at: "2026-06-01T13:00:00+00:00",
};

function apiClient(
  fetchImpl: (url: string, init: RequestInit) => Promise<Response>,
): HermesApiClient {
  return new HermesApiClient({
    baseUrl: "http://copilot.internal",
    token: "tok",
    fetchImpl,
  });
}

describe("handleListCases", () => {
  it("defaults a rep to mine_or_unassigned over open/in_progress", async () => {
    const res = handleListCases(listReq(), deps());
    expect(res.status).toBe(200);
    const ids = ((await res.json()) as { cases: WorkbenchCase[] }).cases.map(
      (c) => c.caseId,
    );
    // unassigned open cases + the rep's own in_progress case; resolved + sales hidden.
    expect(ids).toContain("case_ar_urgent");
    expect(ids).toContain("case_billing_email");
    expect(ids).not.toContain("case_resolved");
    expect(ids).not.toContain("case_sales");
    expect(ids[0]).toBe("case_ar_urgent"); // urgent sorts first
  });

  it("hides another account's case from a rep but shows it to a supervisor", async () => {
    store.assignCase("case_unmatched", "seed-supervisor");

    const repIds = (
      (await handleListCases(listReq(), deps()).json()) as {
        cases: WorkbenchCase[];
      }
    ).cases.map((c) => c.caseId);
    expect(repIds).not.toContain("case_unmatched");

    const supIds = (
      (await handleListCases(
        listReq(),
        deps(session(WORKBENCH_ROLES.supervisor, "seed-supervisor", "supervisor")),
      ).json()) as { cases: WorkbenchCase[] }
    ).cases.map((c) => c.caseId);
    expect(supIds).toContain("case_unmatched");
  });

  it("honours assignee=mine", async () => {
    const ids = (
      (await handleListCases(listReq("?assignee=mine"), deps()).json()) as {
        cases: WorkbenchCase[];
      }
    ).cases.map((c) => c.caseId);
    expect(ids).toEqual(["case_billing_email"]);
  });

  it("parses an explicit status filter (csv)", async () => {
    const ids = (
      (await handleListCases(
        listReq("?assignee=mine&status=resolved"),
        deps(),
      ).json()) as { cases: WorkbenchCase[] }
    ).cases.map((c) => c.caseId);
    expect(ids).toEqual(["case_resolved"]);
  });
});

describe("handleGetCase", () => {
  it("returns the case", async () => {
    const res = handleGetCase("case_ar_urgent", deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { case: WorkbenchCase };
    expect(body.case.caseId).toBe("case_ar_urgent");
  });

  it("404s an unknown case", () => {
    expect(handleGetCase("nope", deps()).status).toBe(404);
  });
});

describe("handleGetThread", () => {
  it("returns case + sorted messages and writes a case_view audit", async () => {
    const res = handleGetThread("case_ar_urgent", deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      case: WorkbenchCase;
      messages: { at: number }[];
    };
    expect(body.case.caseId).toBe("case_ar_urgent");
    expect(body.messages.length).toBeGreaterThan(0);
    const ats = body.messages.map((m) => m.at);
    expect([...ats].sort((a, b) => a - b)).toEqual(ats);
    expect(actions("case_ar_urgent")).toContain("case_view");
  });

  it("404s an unknown case without writing audit", () => {
    expect(handleGetThread("nope", deps()).status).toBe(404);
    expect(actions("nope")).toEqual([]);
  });
});

describe("handleGetAuditLog", () => {
  it("returns the case audit entries", async () => {
    const res = handleGetAuditLog("case_billing_email", deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { entries: { action: string }[] };
    expect(body.entries.length).toBeGreaterThanOrEqual(2);
  });

  it("404s an unknown case", () => {
    expect(handleGetAuditLog("nope", deps()).status).toBe(404);
  });
});

describe("handleClaim", () => {
  it("claims an unassigned case and writes an audit", async () => {
    const res = handleClaim("case_ar_urgent", deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { case: WorkbenchCase };
    expect(body.case.assigneeAccountId).toBe("seed-rep");
    expect(body.case.status).toBe("in_progress");
    expect(actions("case_ar_urgent")).toContain("claim_case");
  });

  it("is idempotent when the actor already holds the case", () => {
    expect(handleClaim("case_billing_email", deps()).status).toBe(200);
  });

  it("409s when another account holds the case", () => {
    const sup = session(WORKBENCH_ROLES.supervisor, "seed-supervisor", "supervisor");
    expect(handleClaim("case_billing_email", deps(sup)).status).toBe(409);
  });

  it("404s an unknown case", () => {
    expect(handleClaim("nope", deps()).status).toBe(404);
  });
});

describe("handleAssign (supervisor/admin only)", () => {
  it("403s a rep", async () => {
    const res = await handleAssign(
      jsonReq({ assigneeAccountId: "seed-rep" }),
      "case_ar_urgent",
      deps(),
    );
    expect(res.status).toBe(403);
  });

  it("assigns as a supervisor and writes an audit", async () => {
    const sup = session(WORKBENCH_ROLES.supervisor, "seed-supervisor", "supervisor");
    const res = await handleAssign(
      jsonReq({ assigneeAccountId: "seed-rep" }),
      "case_ar_urgent",
      deps(sup),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { case: WorkbenchCase };
    expect(body.case.assigneeAccountId).toBe("seed-rep");
    expect(actions("case_ar_urgent")).toContain("assign_case");
  });

  it("400s a missing assigneeAccountId", async () => {
    const admin = session(WORKBENCH_ROLES.admin, "seed-admin", "admin");
    const res = await handleAssign(jsonReq({}), "case_ar_urgent", deps(admin));
    expect(res.status).toBe(400);
  });

  it("404s an unknown case", async () => {
    const sup = session(WORKBENCH_ROLES.supervisor, "seed-supervisor", "supervisor");
    const res = await handleAssign(
      jsonReq({ assigneeAccountId: "seed-rep" }),
      "nope",
      deps(sup),
    );
    expect(res.status).toBe(404);
  });
});

describe("handleResolve", () => {
  it("resolves a case for any authorized user and writes an audit", async () => {
    const res = handleResolve("case_ar_urgent", deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { case: WorkbenchCase };
    expect(body.case.status).toBe("resolved");
    expect(body.case.resolvedByAccountId).toBe("seed-rep");
    expect(actions("case_ar_urgent")).toContain("resolve_case");
  });

  it("404s an unknown case", () => {
    expect(handleResolve("nope", deps()).status).toBe(404);
  });
});

describe("handlePriority (supervisor/admin only)", () => {
  it("403s a rep", async () => {
    const res = await handlePriority(jsonReq({ urgent: false }), "case_ar_urgent", deps());
    expect(res.status).toBe(403);
  });

  it("updates priority as a supervisor and writes an audit", async () => {
    const sup = session(WORKBENCH_ROLES.supervisor, "seed-supervisor", "supervisor");
    const res = await handlePriority(
      jsonReq({ urgent: false }),
      "case_ar_urgent",
      deps(sup),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { case: WorkbenchCase };
    expect(body.case.urgent).toBe(false);
    expect(actions("case_ar_urgent")).toContain("update_priority");
  });

  it("400s a non-boolean urgent", async () => {
    const sup = session(WORKBENCH_ROLES.supervisor, "seed-supervisor", "supervisor");
    const res = await handlePriority(
      jsonReq({ urgent: "yes" }),
      "case_ar_urgent",
      deps(sup),
    );
    expect(res.status).toBe(400);
  });

  it("404s an unknown case", async () => {
    const sup = session(WORKBENCH_ROLES.supervisor, "seed-supervisor", "supervisor");
    const res = await handlePriority(jsonReq({ urgent: true }), "nope", deps(sup));
    expect(res.status).toBe(404);
  });
});

describe("handleContactReason", () => {
  it("updates the contact reason and writes an audit", async () => {
    const res = await handleContactReason(
      jsonReq({ contactReason: "warranty" }),
      "case_ar_urgent",
      deps(),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { case: WorkbenchCase };
    expect(body.case.contactReason).toBe("warranty");
    expect(actions("case_ar_urgent")).toContain("update_contact_reason");
  });

  it("400s an empty contact reason", async () => {
    const res = await handleContactReason(
      jsonReq({ contactReason: "  " }),
      "case_ar_urgent",
      deps(),
    );
    expect(res.status).toBe(400);
  });

  it("404s an unknown case", async () => {
    const res = await handleContactReason(
      jsonReq({ contactReason: "warranty" }),
      "nope",
      deps(),
    );
    expect(res.status).toBe(404);
  });
});

describe("handleListCasesViaApi", () => {
  function client(
    fetchImpl: (url: string, init: RequestInit) => Promise<Response>,
  ): HermesApiClient {
    return new HermesApiClient({
      baseUrl: "http://copilot.internal",
      token: "tok",
      fetchImpl,
    });
  }

  it("returns mapped cases from the per-profile API dispatch", async () => {
    const res = await handleListCasesViaApi(
      listReq(),
      client(async () =>
        new Response(JSON.stringify({ ok: true, data: { cases: [apiCaseRow] } }), {
          status: 200,
        }),
      ),
      deps(),
    );

    expect(res.status).toBe(200);
    const body = (await res.json()) as { cases: WorkbenchCase[] };
    expect(body.cases.map((c) => c.caseId)).toEqual(["case_api"]);
    // snake_case -> camelCase mapping (ADR-0070): identity_summary, sms_session_active, urgency->urgent.
    expect(body.cases[0]?.identitySummary).toBe("Verified: cust_900");
    expect(body.cases[0]?.smsSessionActive).toBe(true);
    expect(body.cases[0]?.urgent).toBe(true);
  });

  it("derives the same role filter and sends it as dispatch params", async () => {
    let sent: { tool: string; action: string; params: unknown } | null = null;
    await handleListCasesViaApi(
      listReq(),
      client(async (_url, init) => {
        sent = JSON.parse(init.body as string);
        return new Response(JSON.stringify({ ok: true, data: { cases: [] } }), {
          status: 200,
        });
      }),
      // A rep defaults to mine_or_unassigned over open/in_progress (ADR-0079).
      deps(session(WORKBENCH_ROLES.rep, "seed-rep")),
    );

    expect(sent).toEqual({
      tool: "toee_workbench_read",
      action: "list_cases",
      params: {
        statuses: ["open", "in_progress"],
        assignee: { mode: "mine_or_unassigned", accountId: "seed-rep" },
      },
    });
  });

  it("maps an upstream failure to a 502 (ADR-0090 error banner)", async () => {
    const res = await handleListCasesViaApi(
      listReq(),
      client(async () => new Response("boom", { status: 500 })),
      deps(),
    );

    expect(res.status).toBe(502);
  });

  it("maps a governed Tool Gate denial to a 403 (ADR-0104 per-class status)", async () => {
    const res = await handleListCasesViaApi(
      listReq(),
      client(async () =>
        new Response(
          JSON.stringify({
            ok: false,
            error: { class: "policy_blocked", message: "denied by Tool Gate" },
          }),
          { status: 200 },
        ),
      ),
      deps(),
    );

    expect(res.status).toBe(403);
  });
});

describe("handleGetCaseViaApi", () => {
  it("returns the mapped case from the per-profile API", async () => {
    const res = await handleGetCaseViaApi(
      apiClient(async () =>
        new Response(JSON.stringify({ ok: true, data: { case: apiCaseRow } }), {
          status: 200,
        }),
      ),
      "case_api",
    );

    expect(res.status).toBe(200);
    const body = (await res.json()) as { case: WorkbenchCase };
    expect(body.case.caseId).toBe("case_api");
    expect(body.case.threadId).toBe("thr_api");
  });

  it("404s when the datastore returns a null case (ADR-0020 empty read)", async () => {
    const res = await handleGetCaseViaApi(
      apiClient(async () =>
        new Response(JSON.stringify({ ok: true, data: { case: null } }), {
          status: 200,
        }),
      ),
      "missing",
    );

    expect(res.status).toBe(404);
  });

  it("maps a governed denial to its per-class status", async () => {
    const res = await handleGetCaseViaApi(
      apiClient(async () =>
        new Response(
          JSON.stringify({ ok: false, error: { class: "policy_blocked", message: "no" } }),
          { status: 200 },
        ),
      ),
      "case_api",
    );

    expect(res.status).toBe(403);
  });
});

describe("handleGetAuditLogViaApi", () => {
  const auditRow = {
    id: "audit_1",
    account_id: "seed-rep",
    actor_username: "rep",
    profile: "internal_copilot",
    action: "claim_case",
    target_type: "case",
    target_id: "case_api",
    details: {},
    created_at: "2026-06-01T12:00:00+00:00",
  };

  // The API path checks the case exists (get_case) before reading its audit log,
  // so 404 parity with the store path holds for an unknown case.
  function clientFor(caseValue: unknown, entries: unknown[]): HermesApiClient {
    return apiClient(async (_url, init) => {
      const sent = JSON.parse(init.body as string) as { action: string };
      const data = sent.action === "get_case" ? { case: caseValue } : { entries };
      return new Response(JSON.stringify({ ok: true, data }), { status: 200 });
    });
  }

  it("returns mapped audit entries", async () => {
    const res = await handleGetAuditLogViaApi(clientFor(apiCaseRow, [auditRow]), "case_api");
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      entries: { entryId: string; actorUsername: string; action: string }[];
    };
    expect(body.entries[0]?.entryId).toBe("audit_1");
    expect(body.entries[0]?.actorUsername).toBe("rep");
    expect(body.entries[0]?.action).toBe("claim_case");
  });

  it("404s when the case is unknown", async () => {
    const res = await handleGetAuditLogViaApi(clientFor(null, []), "missing");
    expect(res.status).toBe(404);
  });
});

describe("handleGetThreadViaApi", () => {
  const messageRow = {
    id: "mt_1",
    customer_thread_id: "thr_api",
    author: "hermes",
    channel: "sms",
    body: "active human reply",
    auto_handled: false,
    active_case_segment: true,
    created_at: "2026-06-01T12:00:00+00:00",
  };

  it("returns the mapped case and timeline from get_thread", async () => {
    const res = await handleGetThreadViaApi(
      apiClient(async () =>
        new Response(
          JSON.stringify({
            ok: true,
            data: { case: apiCaseRow, messages: [messageRow] },
          }),
          { status: 200 },
        ),
      ),
      "case_api",
    );

    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      case: WorkbenchCase;
      messages: { messageId: string; author: string; activeCaseSegment: boolean }[];
    };
    expect(body.case.caseId).toBe("case_api");
    expect(body.messages[0]?.messageId).toBe("mt_1");
    expect(body.messages[0]?.author).toBe("hermes");
    expect(body.messages[0]?.activeCaseSegment).toBe(true);
  });

  it("404s when the datastore returns a null case (ADR-0020 empty read)", async () => {
    const res = await handleGetThreadViaApi(
      apiClient(async () =>
        new Response(
          JSON.stringify({ ok: true, data: { case: null, messages: [] } }),
          { status: 200 },
        ),
      ),
      "missing",
    );

    expect(res.status).toBe(404);
  });

  it("maps a governed denial to its per-class status", async () => {
    const res = await handleGetThreadViaApi(
      apiClient(async () =>
        new Response(
          JSON.stringify({ ok: false, error: { class: "policy_blocked", message: "no" } }),
          { status: 200 },
        ),
      ),
      "case_api",
    );

    expect(res.status).toBe(403);
  });
});
