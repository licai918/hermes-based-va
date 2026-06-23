import { beforeEach, describe, expect, it } from "vitest";
import {
  createInMemoryAccountStore,
  DEV_SEED_PASSWORD,
  type AccountStore,
} from "../auth/account-store";
import {
  SESSION_COOKIE_NAME,
  SESSION_IDLE_MS,
  createSessionToken,
  verifySessionToken,
} from "../auth/session";
import { handleLogin, handleLogout, handleSession } from "./auth-handlers";

const NOW = 1_700_000_000_000;
const SECRET = "test-secret-please-change";

let store: AccountStore;

beforeEach(() => {
  store = createInMemoryAccountStore(0);
});

function deps(now = NOW) {
  return { store, now, secret: SECRET, secure: false };
}

function loginReq(body: unknown): Request {
  return new Request("http://localhost/api/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function tokenFromSetCookie(res: Response): string | null {
  const header = res.headers.get("set-cookie");
  if (!header) return null;
  const match = header.match(new RegExp(`${SESSION_COOKIE_NAME}=([^;]*)`));
  return match ? match[1]! : null;
}

describe("handleLogin", () => {
  it("issues a session cookie on valid credentials", async () => {
    const res = await handleLogin(
      loginReq({ username: "rep", password: DEV_SEED_PASSWORD }),
      deps(),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { user: { username: string; role: string } };
    expect(body.user.username).toBe("rep");
    expect(body.user.role).toBe("customer_service_rep");

    const token = tokenFromSetCookie(res);
    expect(token).toBeTruthy();
    const session = await verifySessionToken(token!, SECRET);
    expect(session).not.toBeNull();
    expect(session!.accountId).toBe("seed-rep");
    expect(session!.role).toBe("customer_service_rep");
    expect(session!.lastActivityAt).toBe(NOW);
  });

  it("rejects a wrong password and records the failed attempt", async () => {
    const res = await handleLogin(
      loginReq({ username: "rep", password: "wrong-password" }),
      deps(),
    );
    expect(res.status).toBe(401);
    expect(tokenFromSetCookie(res)).toBeNull();
    expect(store.getByUsername("rep")!.failedAttempts).toBe(1);
  });

  it("rejects an unknown username without leaking existence", async () => {
    const res = await handleLogin(
      loginReq({ username: "ghost", password: DEV_SEED_PASSWORD }),
      deps(),
    );
    expect(res.status).toBe(401);
  });

  it("locks the account after the max failed attempts", async () => {
    for (let i = 0; i < 5; i++) {
      await handleLogin(loginReq({ username: "rep", password: "nope" }), deps());
    }
    const res = await handleLogin(
      loginReq({ username: "rep", password: DEV_SEED_PASSWORD }),
      deps(),
    );
    expect(res.status).toBe(423);
    expect(tokenFromSetCookie(res)).toBeNull();
  });

  it("refuses a disabled account", async () => {
    store.disable("seed-admin");
    const res = await handleLogin(
      loginReq({ username: "admin", password: DEV_SEED_PASSWORD }),
      deps(),
    );
    expect(res.status).toBe(403);
  });

  it("returns 400 when fields are missing", async () => {
    const res = await handleLogin(loginReq({ username: "rep" }), deps());
    expect(res.status).toBe(400);
  });
});

describe("handleSession", () => {
  it("reports an authenticated session from a valid cookie", async () => {
    const token = await createSessionToken(
      {
        accountId: "seed-rep",
        username: "rep",
        role: "customer_service_rep",
        lastActivityAt: NOW,
      },
      SECRET,
    );
    const req = new Request("http://localhost/api/auth/session", {
      headers: { cookie: `${SESSION_COOKIE_NAME}=${token}` },
    });
    const res = await handleSession(req, deps());
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      authenticated: boolean;
      user?: { username: string; role: string };
    };
    expect(body.authenticated).toBe(true);
    expect(body.user?.username).toBe("rep");
  });

  it("reports unauthenticated when no cookie is present", async () => {
    const req = new Request("http://localhost/api/auth/session");
    const res = await handleSession(req, deps());
    const body = (await res.json()) as { authenticated: boolean };
    expect(body.authenticated).toBe(false);
  });

  it("reports unauthenticated for an idle-expired session", async () => {
    const token = await createSessionToken(
      {
        accountId: "seed-rep",
        username: "rep",
        role: "customer_service_rep",
        lastActivityAt: NOW,
      },
      SECRET,
    );
    const req = new Request("http://localhost/api/auth/session", {
      headers: { cookie: `${SESSION_COOKIE_NAME}=${token}` },
    });
    const res = await handleSession(req, deps(NOW + SESSION_IDLE_MS + 1));
    const body = (await res.json()) as { authenticated: boolean };
    expect(body.authenticated).toBe(false);
  });
});

describe("handleLogout", () => {
  it("clears the session cookie", async () => {
    const res = await handleLogout({ secure: false });
    expect(res.status).toBe(200);
    const header = res.headers.get("set-cookie");
    expect(header).toContain(`${SESSION_COOKIE_NAME}=;`);
    expect(header).toContain("Max-Age=0");
  });
});
