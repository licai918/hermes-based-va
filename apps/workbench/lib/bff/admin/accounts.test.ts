import { beforeEach, describe, expect, it } from "vitest";
import { WORKBENCH_ROLES } from "@toee/shared";
import {
  createInMemoryAccountStore,
  type AccountStore,
} from "../../auth/account-store";
import type { WorkbenchSession } from "../../auth/session";
import { createEvalSeed, createInMemoryEvalStore } from "../../gateway/eval-store";
import { createInMemoryKnowledgeStore } from "../../gateway/knowledge-store";
import type { AdminDeps } from "./deps";
import {
  handleCreateAccount,
  handleDisableAccount,
  handleListAccounts,
  handleUpdateRole,
  type PublicAccount,
} from "./accounts";

const NOW = 1_700_000_000_000;
const VALID_PASSWORD = "ValidPass123!";

// Knowledge + eval stores are untouched by the account handlers; build once.
const knowledge = createInMemoryKnowledgeStore();
const evalStore = createInMemoryEvalStore(createEvalSeed());

let accounts: AccountStore;

beforeEach(() => {
  accounts = createInMemoryAccountStore(0);
});

const session: WorkbenchSession = {
  accountId: "seed-supervisor",
  username: "supervisor",
  role: WORKBENCH_ROLES.supervisor,
  lastActivityAt: NOW,
};

function deps(): AdminDeps {
  return { knowledge, evalStore, accounts, session, now: NOW };
}

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

describe("handleListAccounts", () => {
  it("lists every account and never serializes passwordHash", async () => {
    const res = handleListAccounts(deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { accounts: PublicAccount[] };
    expect(body.accounts.map((a) => a.username).sort()).toEqual([
      "admin",
      "rep",
      "supervisor",
    ]);
    for (const account of body.accounts) {
      expect(account).not.toHaveProperty("passwordHash");
      expect(Object.keys(account).sort()).toEqual([
        "accountId",
        "createdAt",
        "lastLoginAt",
        "role",
        "status",
        "username",
      ]);
    }
  });
});

describe("handleCreateAccount", () => {
  it("400s when a field is missing", async () => {
    const res = await handleCreateAccount(postReq({ username: "newbie" }), deps());
    expect(res.status).toBe(400);
  });

  it("400s an invalid role", async () => {
    const res = await handleCreateAccount(
      postReq({ username: "newbie", role: "wizard", password: VALID_PASSWORD }),
      deps(),
    );
    expect(res.status).toBe(400);
  });

  it("400s a password that fails policy and returns the errors", async () => {
    const res = await handleCreateAccount(
      postReq({ username: "newbie", role: WORKBENCH_ROLES.rep, password: "short" }),
      deps(),
    );
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string; errors: string[] };
    expect(body.error).toBe("password does not meet policy");
    expect(body.errors.length).toBeGreaterThan(0);
  });

  it("409s a duplicate username", async () => {
    const res = await handleCreateAccount(
      postReq({ username: "rep", role: WORKBENCH_ROLES.rep, password: VALID_PASSWORD }),
      deps(),
    );
    expect(res.status).toBe(409);
  });

  it("creates an account (201) without leaking passwordHash", async () => {
    const res = await handleCreateAccount(
      postReq({ username: "fresh", role: WORKBENCH_ROLES.rep, password: VALID_PASSWORD }),
      deps(),
    );
    expect(res.status).toBe(201);
    const body = (await res.json()) as { account: PublicAccount };
    expect(body.account.username).toBe("fresh");
    expect(body.account.role).toBe(WORKBENCH_ROLES.rep);
    expect(body.account.status).toBe("active");
    expect(body.account).not.toHaveProperty("passwordHash");
  });
});

describe("handleUpdateRole", () => {
  it("400s an invalid role", async () => {
    const res = await handleUpdateRole(
      patchReq({ role: "wizard" }),
      "seed-rep",
      deps(),
    );
    expect(res.status).toBe(400);
  });

  it("updates the role and never leaks passwordHash", async () => {
    const res = await handleUpdateRole(
      patchReq({ role: WORKBENCH_ROLES.admin }),
      "seed-rep",
      deps(),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { account: PublicAccount };
    expect(body.account.role).toBe(WORKBENCH_ROLES.admin);
    expect(body.account).not.toHaveProperty("passwordHash");
  });

  it("404s an unknown account", async () => {
    const res = await handleUpdateRole(
      patchReq({ role: WORKBENCH_ROLES.admin }),
      "ghost",
      deps(),
    );
    expect(res.status).toBe(404);
  });
});

describe("handleDisableAccount", () => {
  it("404s an unknown account", () => {
    expect(handleDisableAccount("ghost", deps()).status).toBe(404);
  });

  it("disables an account and never leaks passwordHash", async () => {
    const res = handleDisableAccount("seed-rep", deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { account: PublicAccount };
    expect(body.account.status).toBe("disabled");
    expect(body.account).not.toHaveProperty("passwordHash");
  });
});
