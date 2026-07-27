import { describe, expect, it } from "vitest";
import { WORKBENCH_ROLES } from "@toee/shared";
import { HermesApiClient } from "../../gateway/hermes-api-client";
import {
  handleCreateAccountViaApi,
  handleDisableAccountViaApi,
  handleListAccountsViaApi,
  handleUpdateRoleViaApi,
  type PublicAccount,
} from "./accounts";

const VALID_PASSWORD = "ValidPass123!";

function postReq(body: unknown): Request {
  return new Request("http://localhost/api/admin/accounts", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function patchReq(body: unknown): Request {
  return new Request("http://localhost/api/admin/accounts/x/role", {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

// --- Per-profile API (ADR-0141 Increment 4) ---------------------------------
// 0.0.4 S09 deleted the in-memory AccountStore: the Supervisor Admin account
// routes are the only path, and accounts live in Postgres. These mirror the
// copilot case-write tests: assert the dispatched envelope (tool/action/params + actor on writes),
// the snake_case->PublicAccount mapping, validation parity (400 before dispatch),
// per-error-class status (conflict->409, not_found->404), and the fail-closed
// actor guard (a write with no actor never dispatches the mutation).

// A realistic snake_case workbench_account read-model row (never a password hash).
const apiAccountRow = {
  id: "acct_api",
  account_id: "acct_api",
  username: "fresh",
  role: "customer_service_rep",
  status: "active",
  created_at: "2026-06-01T12:00:00+00:00",
  updated_at: "2026-06-01T12:00:00+00:00",
};

// The acting supervisor baked into a write client (ADR-0141): writes carry it,
// the actor-less client omits it to exercise the fail-closed guard.
const WRITE_ACTOR = "seed-supervisor";

type SentDispatch = {
  tool: string;
  action: string;
  params: Record<string, unknown>;
  actor_account_id?: string;
};

function apiClient(
  fetchImpl: (url: string, init: RequestInit) => Promise<Response>,
  actorAccountId?: string,
): HermesApiClient {
  return new HermesApiClient({
    baseUrl: "http://admin.internal",
    token: "tok",
    actorAccountId,
    fetchImpl,
  });
}

function writeClient(
  data: unknown,
  capture?: (sent: SentDispatch) => void,
): HermesApiClient {
  return apiClient(async (_url, init) => {
    const sent = JSON.parse(init.body as string) as SentDispatch;
    capture?.(sent);
    return new Response(JSON.stringify({ ok: true, data }), { status: 200 });
  }, WRITE_ACTOR);
}

function denyOn(action: string, errorClass: string): HermesApiClient {
  return apiClient(async (_url, init) => {
    const sent = JSON.parse(init.body as string) as SentDispatch;
    if (sent.action === action) {
      return new Response(
        JSON.stringify({ ok: false, error: { class: errorClass, message: "no" } }),
        { status: 200 },
      );
    }
    return new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 });
  }, WRITE_ACTOR);
}

// No actor baked in: governed writes must be refused before the mutation fires.
function actorlessClient(seen: string[]): HermesApiClient {
  return apiClient(async (_url, init) => {
    const sent = JSON.parse(init.body as string) as SentDispatch;
    seen.push(sent.action);
    return new Response(
      JSON.stringify({ ok: true, data: { account: apiAccountRow } }),
      { status: 200 },
    );
  });
}

function countingClient(counter: { dispatched: boolean }): HermesApiClient {
  return apiClient(async () => {
    counter.dispatched = true;
    return new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 });
  }, WRITE_ACTOR);
}

describe("handleListAccountsViaApi", () => {
  it("maps datastore rows onto PublicAccount and never leaks passwordHash", async () => {
    const client = apiClient(async () =>
      new Response(JSON.stringify({ ok: true, data: { accounts: [apiAccountRow] } }), {
        status: 200,
      }),
    );
    const res = await handleListAccountsViaApi(client);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { accounts: PublicAccount[] };
    expect(body.accounts).toEqual([
      {
        accountId: "acct_api",
        username: "fresh",
        role: WORKBENCH_ROLES.rep,
        status: "active",
        lastLoginAt: null,
        createdAt: Date.parse("2026-06-01T12:00:00+00:00"),
      },
    ]);
    expect(body.accounts[0]).not.toHaveProperty("passwordHash");
  });

  it("maps a governed error to its per-class status", async () => {
    const client = apiClient(async () =>
      new Response(
        JSON.stringify({ ok: false, error: { class: "policy_blocked", message: "no" } }),
        { status: 200 },
      ),
    );
    expect((await handleListAccountsViaApi(client)).status).toBe(403);
  });
});

describe("handleCreateAccountViaApi", () => {
  it("hashes the password, dispatches create_account with the actor, and 201s the mapped account", async () => {
    let sent: SentDispatch | null = null;
    const client = writeClient(
      { account_id: "acct_api", created: true, account: apiAccountRow },
      (s) => {
        sent = s;
      },
    );
    const res = await handleCreateAccountViaApi(
      postReq({ username: "fresh", role: WORKBENCH_ROLES.rep, password: VALID_PASSWORD }),
      client,
    );
    expect(res.status).toBe(201);
    const body = (await res.json()) as { account: PublicAccount };
    expect(body.account.username).toBe("fresh");
    expect(body.account.status).toBe("active");
    expect(body.account).not.toHaveProperty("passwordHash");
    const s = sent as SentDispatch | null;
    expect(s?.tool).toBe("toee_workbench_admin");
    expect(s?.action).toBe("create_account");
    expect(s?.actor_account_id).toBe(WRITE_ACTOR);
    expect(s?.params.username).toBe("fresh");
    expect(s?.params.role).toBe(WORKBENCH_ROLES.rep);
    // The plaintext password never crosses the wire; a derived password_hash does.
    expect(s?.params.password).toBeUndefined();
    expect(typeof s?.params.password_hash).toBe("string");
    expect(s?.params.password_hash).not.toBe(VALID_PASSWORD);
  });

  it("400s a missing field before any dispatch", async () => {
    const counter = { dispatched: false };
    const res = await handleCreateAccountViaApi(
      postReq({ username: "fresh" }),
      countingClient(counter),
    );
    expect(res.status).toBe(400);
    expect(counter.dispatched).toBe(false);
  });

  it("400s an invalid role before any dispatch", async () => {
    const counter = { dispatched: false };
    const res = await handleCreateAccountViaApi(
      postReq({ username: "fresh", role: "wizard", password: VALID_PASSWORD }),
      countingClient(counter),
    );
    expect(res.status).toBe(400);
    expect(counter.dispatched).toBe(false);
  });

  it("400s a password that fails policy and returns the errors before any dispatch", async () => {
    const counter = { dispatched: false };
    const res = await handleCreateAccountViaApi(
      postReq({ username: "fresh", role: WORKBENCH_ROLES.rep, password: "short" }),
      countingClient(counter),
    );
    expect(res.status).toBe(400);
    expect(counter.dispatched).toBe(false);
    const body = (await res.json()) as { error: string; errors: string[] };
    expect(body.error).toBe("password does not meet policy");
    expect(body.errors.length).toBeGreaterThan(0);
  });

  it("409s a duplicate username (governed conflict)", async () => {
    const res = await handleCreateAccountViaApi(
      postReq({ username: "rep", role: WORKBENCH_ROLES.rep, password: VALID_PASSWORD }),
      denyOn("create_account", "conflict"),
    );
    expect(res.status).toBe(409);
  });
});

describe("handleUpdateRoleViaApi", () => {
  it("dispatches update_account_role with the actor and 200s the mapped account", async () => {
    let sent: SentDispatch | null = null;
    const client = writeClient(
      {
        account_id: "acct_api",
        role: WORKBENCH_ROLES.admin,
        updated: true,
        account: { ...apiAccountRow, role: "workbench_admin" },
      },
      (s) => {
        sent = s;
      },
    );
    const res = await handleUpdateRoleViaApi(
      patchReq({ role: WORKBENCH_ROLES.admin }),
      client,
      "acct_api",
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { account: PublicAccount };
    expect(body.account.role).toBe(WORKBENCH_ROLES.admin);
    const s = sent as SentDispatch | null;
    expect(s?.action).toBe("update_account_role");
    expect(s?.params).toEqual({ account_id: "acct_api", role: WORKBENCH_ROLES.admin });
    expect(s?.actor_account_id).toBe(WRITE_ACTOR);
  });

  it("400s an invalid role before any dispatch", async () => {
    const counter = { dispatched: false };
    const res = await handleUpdateRoleViaApi(
      patchReq({ role: "wizard" }),
      countingClient(counter),
      "acct_api",
    );
    expect(res.status).toBe(400);
    expect(counter.dispatched).toBe(false);
  });

  it("404s an unknown account (governed not_found)", async () => {
    const res = await handleUpdateRoleViaApi(
      patchReq({ role: WORKBENCH_ROLES.admin }),
      denyOn("update_account_role", "not_found"),
      "ghost",
    );
    expect(res.status).toBe(404);
  });
});

describe("handleDisableAccountViaApi", () => {
  it("dispatches disable_account with the actor and 200s the mapped account", async () => {
    let sent: SentDispatch | null = null;
    const client = writeClient(
      {
        account_id: "acct_api",
        disabled: true,
        account: { ...apiAccountRow, status: "disabled" },
      },
      (s) => {
        sent = s;
      },
    );
    const res = await handleDisableAccountViaApi(client, "acct_api");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { account: PublicAccount };
    expect(body.account.status).toBe("disabled");
    const s = sent as SentDispatch | null;
    expect(s?.action).toBe("disable_account");
    expect(s?.params).toEqual({ account_id: "acct_api" });
    expect(s?.actor_account_id).toBe(WRITE_ACTOR);
  });

  it("404s an unknown account (governed not_found)", async () => {
    const res = await handleDisableAccountViaApi(
      denyOn("disable_account", "not_found"),
      "ghost",
    );
    expect(res.status).toBe(404);
  });
});

describe("governed admin writes require an actor (BFF defense-in-depth)", () => {
  it("rejects create and never dispatches the mutation", async () => {
    const seen: string[] = [];
    const res = await handleCreateAccountViaApi(
      postReq({ username: "fresh", role: WORKBENCH_ROLES.rep, password: VALID_PASSWORD }),
      actorlessClient(seen),
    );
    expect(res.status).toBe(403);
    expect(((await res.json()) as { errorClass?: string }).errorClass).toBe(
      "policy_blocked",
    );
    expect(seen).not.toContain("create_account");
  });

  it("rejects update-role and never dispatches the mutation", async () => {
    const seen: string[] = [];
    const res = await handleUpdateRoleViaApi(
      patchReq({ role: WORKBENCH_ROLES.admin }),
      actorlessClient(seen),
      "acct_api",
    );
    expect(res.status).toBe(403);
    expect(seen).not.toContain("update_account_role");
  });

  it("rejects disable and never dispatches the mutation", async () => {
    const seen: string[] = [];
    const res = await handleDisableAccountViaApi(actorlessClient(seen), "acct_api");
    expect(res.status).toBe(403);
    expect(seen).not.toContain("disable_account");
  });
});
