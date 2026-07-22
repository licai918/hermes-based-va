import { describe, expect, it } from "vitest";
import { WORKBENCH_ROLES, type WorkbenchRoleId } from "@toee/shared";
import type { WorkbenchSession } from "../../auth/session";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import type { WorkbenchCase } from "../../gateway/types";
import {
  handleAssignViaApi,
  handleClaimViaApi,
  handleContactReasonViaApi,
  handleGetAuditLogViaApi,
  handleGetCaseViaApi,
  handleGetThreadViaApi,
  handleListCasesViaApi,
  handlePriorityViaApi,
  handleResolveViaApi,
} from "./cases";

// 0.0.4 S09: the in-memory GatewayStore is gone, so every case behavior is asserted
// at the HTTP-client seam -- the dispatched `{ tool, action, params }` envelope and
// the mapped response. What the datastore does with that envelope (queue ordering,
// the case_view audit row, claim atomicity) is pinned by the runtime suite.

const NOW = 1_700_000_000_000;

function session(
  role: WorkbenchRoleId = WORKBENCH_ROLES.rep,
  accountId = "seed-rep",
  username = "rep",
): WorkbenchSession {
  return { accountId, username, role, lastActivityAt: NOW };
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

// The acting account baked into a write client (ADR-0141). Reads pass no actor
// (fail-open); writes must, so the write-path helpers below set this.
const WRITE_ACTOR = "seed-rep";

function apiClient(
  fetchImpl: (url: string, init: RequestInit) => Promise<Response>,
  actorAccountId?: string,
): HermesApiClient {
  return new HermesApiClient({
    baseUrl: "http://copilot.internal",
    token: "tok",
    actorAccountId,
    fetchImpl,
  });
}

const sup = () => session(WORKBENCH_ROLES.supervisor, "seed-supervisor", "supervisor");

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
      session(),
    );

    expect(res.status).toBe(200);
    const body = (await res.json()) as { cases: WorkbenchCase[] };
    expect(body.cases.map((c) => c.caseId)).toEqual(["case_api"]);
    // snake_case -> camelCase mapping (ADR-0070): identity_summary, sms_session_active, urgency->urgent.
    expect(body.cases[0]?.identitySummary).toBe("Verified: cust_900");
    expect(body.cases[0]?.smsSessionActive).toBe(true);
    expect(body.cases[0]?.urgent).toBe(true);
  });

  // The ADR-0079 queue filter is the one piece of queue logic that stayed in the
  // BFF: the role default is decided here and the datastore applies it. These pin
  // the derived params on the wire -- the store-seam assertions they replace
  // ("defaults a rep to mine_or_unassigned", "shows another account's case to a
  // supervisor", "honours assignee=mine", "parses a csv status filter") observed
  // the same decisions through createInMemoryGatewayStore's filtering.
  async function sentFilterFor(
    query: string,
    who: WorkbenchSession,
  ): Promise<{ tool: string; action: string; params: unknown }> {
    let sent: { tool: string; action: string; params: unknown } | null = null;
    await handleListCasesViaApi(
      listReq(query),
      client(async (_url, init) => {
        sent = JSON.parse(init.body as string);
        return new Response(JSON.stringify({ ok: true, data: { cases: [] } }), {
          status: 200,
        });
      }),
      who,
    );
    return sent as unknown as { tool: string; action: string; params: unknown };
  }

  it("defaults a rep to mine_or_unassigned over open/in_progress", async () => {
    expect(await sentFilterFor("", session(WORKBENCH_ROLES.rep, "seed-rep"))).toEqual({
      tool: "toee_workbench_read",
      action: "list_cases",
      params: {
        statuses: ["open", "in_progress"],
        assignee: { mode: "mine_or_unassigned", accountId: "seed-rep" },
      },
    });
  });

  it("defaults a supervisor to the whole queue (mode all, no accountId)", async () => {
    const sent = await sentFilterFor("", sup());
    expect(sent.params).toEqual({
      statuses: ["open", "in_progress"],
      assignee: { mode: "all" },
    });
  });

  it("honours an explicit assignee=mine and scopes it to the caller", async () => {
    const sent = await sentFilterFor("?assignee=mine", sup());
    expect(sent.params).toEqual({
      statuses: ["open", "in_progress"],
      // Even a supervisor asking for "mine" gets their OWN account id, never a
      // client-supplied one.
      assignee: { mode: "mine", accountId: "seed-supervisor" },
    });
  });

  it("honours assignee=unassigned without attaching an account id", async () => {
    const sent = await sentFilterFor("?assignee=unassigned", session());
    expect(sent.params).toEqual({
      statuses: ["open", "in_progress"],
      assignee: { mode: "unassigned" },
    });
  });

  it("parses an explicit status filter (csv) and drops unknown values", async () => {
    const sent = await sentFilterFor("?status=resolved,bogus", session());
    expect(sent.params).toMatchObject({ statuses: ["resolved"] });
  });

  it("falls back to the default statuses when every value is unknown", async () => {
    const sent = await sentFilterFor("?status=bogus", session());
    expect(sent.params).toMatchObject({ statuses: ["open", "in_progress"] });
  });

  it("maps an upstream failure to a 502 (ADR-0090 error banner)", async () => {
    const res = await handleListCasesViaApi(
      listReq(),
      client(async () => new Response("boom", { status: 500 })),
      session(),
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
      session(),
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

// Slice 35 Increment 3: the governed case writes over the per-profile API. Each
// pre-reads get_case for 404 parity (the datastore raises on a missing case, which
// the store path returns as 404), then dispatches the toee_case_manage mutation and
// maps the fresh case the handler returns. Role/body validation matches the store
// path exactly and runs before any dispatch.
type SentDispatch = {
  tool: string;
  action: string;
  params: Record<string, unknown>;
  actor_account_id?: string;
};

// Write clients bake in WRITE_ACTOR so the governed mutation passes the fail-closed
// actor guard (dispatchWrite) and the dispatched body carries actor_account_id.
function writeClient(
  caseValue: unknown,
  mutationData: unknown,
  capture?: (sent: SentDispatch) => void,
): HermesApiClient {
  return apiClient(async (_url, init) => {
    const sent = JSON.parse(init.body as string) as SentDispatch;
    capture?.(sent);
    const data = sent.action === "get_case" ? { case: caseValue } : mutationData;
    return new Response(JSON.stringify({ ok: true, data }), { status: 200 });
  }, WRITE_ACTOR);
}

function denyOn(action: string, errorClass: string): HermesApiClient {
  // get_case succeeds (so 404/role gates pass) but the mutation is denied, proving
  // the governed error maps to its ADR-0104 per-class status.
  return apiClient(async (_url, init) => {
    const sent = JSON.parse(init.body as string) as SentDispatch;
    if (sent.action === action) {
      return new Response(
        JSON.stringify({ ok: false, error: { class: errorClass, message: "no" } }),
        { status: 200 },
      );
    }
    return new Response(JSON.stringify({ ok: true, data: { case: apiCaseRow } }), {
      status: 200,
    });
  }, WRITE_ACTOR);
}

describe("handleClaimViaApi", () => {
  it("claims an unassigned case and returns the mapped fresh case", async () => {
    let claim: SentDispatch | null = null;
    const client = writeClient(
      apiCaseRow,
      {
        case: { ...apiCaseRow, assignee_account_id: "seed-rep", status: "in_progress" },
        claimed: true,
      },
      (sent) => {
        if (sent.action === "claim_case") claim = sent;
      },
    );
    const res = await handleClaimViaApi(client, "case_api", session());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { case: WorkbenchCase };
    expect(body.case.assigneeAccountId).toBe("seed-rep");
    expect(body.case.status).toBe("in_progress");
    const sent = claim as SentDispatch | null;
    expect(sent?.tool).toBe("toee_case_manage");
    expect(sent?.params).toEqual({ case_id: "case_api" });
    // I1 positive parity: the governed write carries the acting account.
    expect(sent?.actor_account_id).toBe(WRITE_ACTOR);
  });

  it("is idempotent when the actor already holds the case", async () => {
    const mine = { ...apiCaseRow, assignee_account_id: "seed-rep" };
    const res = await handleClaimViaApi(
      writeClient(mine, { case: mine, claimed: true }),
      "case_api",
      session(),
    );
    expect(res.status).toBe(200);
  });

  it("409s when another account holds the case", async () => {
    const held = { ...apiCaseRow, assignee_account_id: "seed-other" };
    const res = await handleClaimViaApi(
      writeClient(held, { case: held, claimed: true }),
      "case_api",
      session(),
    );
    expect(res.status).toBe(409);
  });

  it("404s an unknown case (null pre-read)", async () => {
    const res = await handleClaimViaApi(writeClient(null, {}), "missing", session());
    expect(res.status).toBe(404);
  });

  it("maps a governed denial to its per-class status", async () => {
    const res = await handleClaimViaApi(denyOn("claim_case", "policy_blocked"), "case_api", session());
    expect(res.status).toBe(403);
  });

  it("maps a datastore conflict (race past the pre-read) to 409", async () => {
    // The BFF pre-read is no longer the sole conflict guard (I2): a concurrent
    // claim that slips past it is denied atomically by the datastore with a
    // governed `conflict`, which must surface as 409 — not a silent 200 steal.
    const res = await handleClaimViaApi(denyOn("claim_case", "conflict"), "case_api", session());
    expect(res.status).toBe(409);
  });

  it("maps a datastore not_found (delete race) to 404", async () => {
    const res = await handleClaimViaApi(denyOn("claim_case", "not_found"), "case_api", session());
    expect(res.status).toBe(404);
  });
});

describe("handleAssignViaApi (supervisor/admin only)", () => {
  it("403s a rep before any dispatch", async () => {
    let dispatched = false;
    const client = apiClient(async () => {
      dispatched = true;
      return new Response(JSON.stringify({ ok: true, data: { case: apiCaseRow } }), {
        status: 200,
      });
    });
    const res = await handleAssignViaApi(
      jsonReq({ assigneeAccountId: "seed-rep" }),
      client,
      "case_api",
      session(),
    );
    expect(res.status).toBe(403);
    expect(dispatched).toBe(false);
  });

  it("assigns as a supervisor and dispatches assignee_id", async () => {
    let assign: SentDispatch | null = null;
    const client = writeClient(
      apiCaseRow,
      { case: { ...apiCaseRow, assignee_account_id: "seed-rep" }, assigned: true },
      (sent) => {
        if (sent.action === "assign_case") assign = sent;
      },
    );
    const res = await handleAssignViaApi(
      jsonReq({ assigneeAccountId: "seed-rep" }),
      client,
      "case_api",
      sup(),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { case: WorkbenchCase };
    expect(body.case.assigneeAccountId).toBe("seed-rep");
    const sent = assign as SentDispatch | null;
    expect(sent?.params).toEqual({ case_id: "case_api", assignee_id: "seed-rep" });
    expect(sent?.actor_account_id).toBe(WRITE_ACTOR);
  });

  it("400s a missing assigneeAccountId", async () => {
    const res = await handleAssignViaApi(
      jsonReq({}),
      writeClient(apiCaseRow, {}),
      "case_api",
      sup(),
    );
    expect(res.status).toBe(400);
  });

  it("404s an unknown case", async () => {
    const res = await handleAssignViaApi(
      jsonReq({ assigneeAccountId: "seed-rep" }),
      writeClient(null, {}),
      "missing",
      sup(),
    );
    expect(res.status).toBe(404);
  });
});

describe("handleResolveViaApi", () => {
  it("resolves a case and returns the mapped fresh case", async () => {
    let resolve: SentDispatch | null = null;
    const client = writeClient(
      apiCaseRow,
      {
        case: { ...apiCaseRow, status: "resolved", resolved_by_account_id: "seed-rep" },
        status: "resolved",
      },
      (sent) => {
        if (sent.action === "resolve_case") resolve = sent;
      },
    );
    const res = await handleResolveViaApi(client, "case_api");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { case: WorkbenchCase };
    expect(body.case.status).toBe("resolved");
    const sent = resolve as SentDispatch | null;
    expect(sent?.params).toEqual({ case_id: "case_api" });
    expect(sent?.actor_account_id).toBe(WRITE_ACTOR);
  });

  it("404s an unknown case", async () => {
    const res = await handleResolveViaApi(writeClient(null, {}), "missing");
    expect(res.status).toBe(404);
  });

  it("maps a governed denial to its per-class status", async () => {
    const res = await handleResolveViaApi(denyOn("resolve_case", "vendor_timeout"), "case_api");
    expect(res.status).toBe(504);
  });
});

describe("handlePriorityViaApi (supervisor/admin only)", () => {
  it("403s a rep", async () => {
    const res = await handlePriorityViaApi(
      jsonReq({ urgent: true }),
      writeClient(apiCaseRow, {}),
      "case_api",
      session(),
    );
    expect(res.status).toBe(403);
  });

  it("maps urgent boolean to the priority label and returns the case", async () => {
    let pr: SentDispatch | null = null;
    const client = writeClient(
      apiCaseRow,
      { case: { ...apiCaseRow, urgency: "normal", urgent: false }, updated: true },
      (sent) => {
        if (sent.action === "update_priority") pr = sent;
      },
    );
    const res = await handlePriorityViaApi(
      jsonReq({ urgent: false }),
      client,
      "case_api",
      sup(),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { case: WorkbenchCase };
    expect(body.case.urgent).toBe(false);
    const sent = pr as SentDispatch | null;
    expect(sent?.params).toEqual({ case_id: "case_api", priority: "normal" });
    expect(sent?.actor_account_id).toBe(WRITE_ACTOR);
  });

  it("400s a non-boolean urgent", async () => {
    const res = await handlePriorityViaApi(
      jsonReq({ urgent: "yes" }),
      writeClient(apiCaseRow, {}),
      "case_api",
      sup(),
    );
    expect(res.status).toBe(400);
  });

  it("404s an unknown case", async () => {
    const res = await handlePriorityViaApi(
      jsonReq({ urgent: true }),
      writeClient(null, {}),
      "missing",
      sup(),
    );
    expect(res.status).toBe(404);
  });
});

describe("handleContactReasonViaApi", () => {
  it("updates the contact reason and dispatches contact_reason", async () => {
    let cr: SentDispatch | null = null;
    const client = writeClient(
      apiCaseRow,
      { case: { ...apiCaseRow, contact_reason: "warranty" }, updated: true },
      (sent) => {
        if (sent.action === "update_contact_reason") cr = sent;
      },
    );
    const res = await handleContactReasonViaApi(
      jsonReq({ contactReason: "warranty" }),
      client,
      "case_api",
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { case: WorkbenchCase };
    expect(body.case.contactReason).toBe("warranty");
    const sent = cr as SentDispatch | null;
    expect(sent?.params).toEqual({ case_id: "case_api", contact_reason: "warranty" });
    expect(sent?.actor_account_id).toBe(WRITE_ACTOR);
  });

  it("400s an empty contact reason", async () => {
    const res = await handleContactReasonViaApi(
      jsonReq({ contactReason: "  " }),
      writeClient(apiCaseRow, {}),
      "case_api",
    );
    expect(res.status).toBe(400);
  });

  it("404s an unknown case", async () => {
    const res = await handleContactReasonViaApi(
      jsonReq({ contactReason: "warranty" }),
      writeClient(null, {}),
      "missing",
    );
    expect(res.status).toBe(404);
  });
});

// I1 (ADR-0141 fail-closed actor): defense-in-depth in the BFF. A governed write
// dispatched through a client with NO actor is denied before it ever calls the
// mutation — so a write route that forgot to wire session.accountId can't
// reintroduce a NULL-actor governed write — while reads stay fail-open.
describe("governed case writes require an actor (BFF defense-in-depth)", () => {
  // No actorAccountId. get_case (the pre-read) succeeds so the write reaches — and
  // is stopped at — its actor guard, not the 404/role gates; `seen` records every
  // dispatched action so a test can assert the mutation never fired.
  function actorlessClient(seen: string[]): HermesApiClient {
    return apiClient(async (_url, init) => {
      const sent = JSON.parse(init.body as string) as SentDispatch;
      seen.push(sent.action);
      return new Response(
        JSON.stringify({ ok: true, data: { case: apiCaseRow } }),
        { status: 200 },
      );
    });
  }

  it("rejects a claim and never dispatches the mutation", async () => {
    const seen: string[] = [];
    const res = await handleClaimViaApi(actorlessClient(seen), "case_api", session());
    expect(res.status).toBe(403);
    expect(((await res.json()) as { errorClass?: string }).errorClass).toBe(
      "policy_blocked",
    );
    expect(seen).not.toContain("claim_case");
  });

  it("rejects an assign once the role gate passes and never dispatches the mutation", async () => {
    const seen: string[] = [];
    const res = await handleAssignViaApi(
      jsonReq({ assigneeAccountId: "seed-rep" }),
      actorlessClient(seen),
      "case_api",
      sup(),
    );
    expect(res.status).toBe(403);
    expect(seen).not.toContain("assign_case");
  });

  it("still allows a read with no actor (reads stay fail-open)", async () => {
    const res = await handleGetCaseViaApi(
      apiClient(async () =>
        new Response(JSON.stringify({ ok: true, data: { case: apiCaseRow } }), {
          status: 200,
        }),
      ),
      "case_api",
    );
    expect(res.status).toBe(200);
  });
});
