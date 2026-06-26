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
import { HermesApiClient } from "../gateway/hermes-api-client";
import {
  handleLogin,
  handleLoginViaApi,
  handleLogout,
  handleSession,
} from "./auth-handlers";

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

// --- Per-profile API cutover (ADR-0144 Increment 5) -------------------------
// When the admin per-profile API is configured the login route authenticates
// against Postgres via toee_workbench_admin.authenticate instead of the in-memory
// store. These mirror the admin ViaApi tests: assert the dispatched envelope
// (plaintext password sent, never a hash, no actor — authenticate is pre-auth),
// the session issued on success, and parity error responses (401 generic for
// bad/unknown, 403 for disabled) with no Set-Cookie.

// A wire-safe authenticate success row from the datastore (never a password hash).
const authAccountRow = {
  id: "acct_login",
  account_id: "acct_login",
  username: "rep",
  role: "customer_service_rep",
  status: "active",
  created_at: "2026-06-01T12:00:00+00:00",
  updated_at: "2026-06-01T12:00:00+00:00",
  last_login_at: "2026-06-26T00:00:00+00:00",
};

type SentDispatch = {
  tool: string;
  action: string;
  params: Record<string, unknown>;
  actor_account_id?: string;
};

// The login client carries NO actor (pre-auth): authenticate uses dispatch, not
// dispatchWrite, so no acting account is required.
function loginClient(
  responder: (sent: SentDispatch) => { ok: boolean; data?: unknown; error?: unknown },
  capture?: (sent: SentDispatch) => void,
): HermesApiClient {
  return new HermesApiClient({
    baseUrl: "http://admin.internal",
    token: "tok",
    fetchImpl: async (_url, init) => {
      const sent = JSON.parse(init.body as string) as SentDispatch;
      capture?.(sent);
      return new Response(JSON.stringify(responder(sent)), { status: 200 });
    },
  });
}

function viaApiDeps(now = NOW) {
  return { now, secret: SECRET, secure: false };
}

describe("handleLoginViaApi", () => {
  it("dispatches authenticate with the plaintext password (never a hash) and no actor", async () => {
    let sent: SentDispatch | null = null;
    const client = loginClient(
      () => ({ ok: true, data: { account: authAccountRow } }),
      (s) => {
        sent = s;
      },
    );
    await handleLoginViaApi(
      loginReq({ username: "rep", password: DEV_SEED_PASSWORD }),
      client,
      viaApiDeps(),
    );
    const s = sent as SentDispatch | null;
    expect(s?.tool).toBe("toee_workbench_admin");
    expect(s?.action).toBe("authenticate");
    expect(s?.params.username).toBe("rep");
    expect(s?.params.password).toBe(DEV_SEED_PASSWORD);
    // The hash is computed server-side: the BFF sends NO password_hash, and being
    // pre-auth it attaches NO actor_account_id.
    expect(s?.params.password_hash).toBeUndefined();
    expect(s?.actor_account_id).toBeUndefined();
  });

  it("issues a session cookie on valid credentials and never returns a hash", async () => {
    const client = loginClient(() => ({ ok: true, data: { account: authAccountRow } }));
    const res = await handleLoginViaApi(
      loginReq({ username: "rep", password: DEV_SEED_PASSWORD }),
      client,
      viaApiDeps(),
    );
    expect(res.status).toBe(200);
    const text = await res.clone().text();
    expect(text).not.toContain("hash");
    const body = (await res.json()) as { user: { accountId: string; username: string; role: string } };
    expect(body.user.accountId).toBe("acct_login");
    expect(body.user.username).toBe("rep");
    expect(body.user.role).toBe("customer_service_rep");

    const token = tokenFromSetCookie(res);
    expect(token).toBeTruthy();
    const session = await verifySessionToken(token!, SECRET);
    expect(session).not.toBeNull();
    expect(session!.accountId).toBe("acct_login");
    expect(session!.role).toBe("customer_service_rep");
    expect(session!.lastActivityAt).toBe(NOW);
  });

  it("rejects a bad password with a generic 401 and no session", async () => {
    const client = loginClient(() => ({
      ok: false,
      error: { class: "unauthenticated", message: "invalid credentials." },
    }));
    const res = await handleLoginViaApi(
      loginReq({ username: "rep", password: "wrong" }),
      client,
      viaApiDeps(),
    );
    expect(res.status).toBe(401);
    expect(tokenFromSetCookie(res)).toBeNull();
    expect(((await res.json()) as { error: string }).error).toBe("invalid credentials");
  });

  it("returns the same generic 401 for an unknown user (no enumeration)", async () => {
    const client = loginClient(() => ({
      ok: false,
      error: { class: "unauthenticated", message: "invalid credentials." },
    }));
    const res = await handleLoginViaApi(
      loginReq({ username: "ghost", password: DEV_SEED_PASSWORD }),
      client,
      viaApiDeps(),
    );
    expect(res.status).toBe(401);
    expect(((await res.json()) as { error: string }).error).toBe("invalid credentials");
  });

  it("refuses a disabled account with 403 and no session", async () => {
    const client = loginClient(() => ({
      ok: false,
      error: { class: "policy_blocked", message: "account disabled." },
    }));
    const res = await handleLoginViaApi(
      loginReq({ username: "admin", password: DEV_SEED_PASSWORD }),
      client,
      viaApiDeps(),
    );
    expect(res.status).toBe(403);
    expect(tokenFromSetCookie(res)).toBeNull();
    expect(((await res.json()) as { error: string }).error).toBe("account disabled");
  });

  it("returns 400 when fields are missing before any dispatch", async () => {
    let dispatched = false;
    const client = loginClient(() => {
      dispatched = true;
      return { ok: true, data: { account: authAccountRow } };
    });
    const res = await handleLoginViaApi(loginReq({ username: "rep" }), client, viaApiDeps());
    expect(res.status).toBe(400);
    expect(dispatched).toBe(false);
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
