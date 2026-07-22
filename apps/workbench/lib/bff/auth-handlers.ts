// Login / logout / session BFF handlers (ADR-0017 local username+password,
// ADR-0018 lockout + idle timeout, ADR-0093 signed cookie). Pure functions with
// injected deps (store/clock/secret) so they are unit-testable; the thin route
// files under app/api/auth/* wire in the real singletons.
import type { AccountStore } from "../auth/account-store";
import { verifyPassword } from "../auth/password";
import {
  SESSION_COOKIE_NAME,
  SESSION_IDLE_MS,
  createSessionToken,
  isSessionExpired,
  verifySessionToken,
} from "../auth/session";
import { HermesApiError, type HermesApiClient } from "../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../gateway/hermes-error";
import { buildClearedSessionCookie, buildSessionCookie } from "./cookie";
import { mapPublicAccount } from "./admin/accounts";
import { json, problem } from "./respond";
import { parseCookies } from "./with-session";

export type AuthDeps = {
  store: AccountStore;
  now: number;
  secret: string;
  secure: boolean;
};

type LoginBody = { username: string; password: string };

function parseLoginBody(value: unknown): LoginBody | null {
  if (typeof value !== "object" || value === null) return null;
  const record = value as Record<string, unknown>;
  if (typeof record.username !== "string" || typeof record.password !== "string") {
    return null;
  }
  if (record.username.length === 0 || record.password.length === 0) return null;
  return { username: record.username, password: record.password };
}

export async function handleLogin(req: Request, deps: AuthDeps): Promise<Response> {
  let raw: unknown;
  try {
    raw = await req.json();
  } catch {
    return problem(400, "invalid request body");
  }
  const body = parseLoginBody(raw);
  if (!body) return problem(400, "username and password are required");

  const account = deps.store.getByUsername(body.username);
  // Generic 401 for unknown users so we don't leak which usernames exist.
  if (!account) return problem(401, "invalid credentials");

  if (account.status === "disabled") return problem(403, "account disabled");

  if (deps.store.isLocked(account, deps.now)) {
    return problem(423, "account temporarily locked");
  }

  if (!verifyPassword(body.password, account.passwordHash)) {
    deps.store.recordFailedLogin(account.accountId, deps.now);
    return problem(401, "invalid credentials");
  }

  deps.store.recordSuccessfulLogin(account.accountId, deps.now);
  const token = await createSessionToken(
    {
      accountId: account.accountId,
      username: account.username,
      role: account.role,
      lastActivityAt: deps.now,
    },
    deps.secret,
  );

  return json(
    {
      user: {
        accountId: account.accountId,
        username: account.username,
        role: account.role,
      },
    },
    {
      headers: {
        "set-cookie": buildSessionCookie(token, {
          maxAgeSeconds: Math.floor(SESSION_IDLE_MS / 1000),
          secure: deps.secure,
        }),
      },
    },
  );
}

// --- Per-profile API cutover (ADR-0144 Increment 5) --------------------------
// When the admin per-profile API is configured the login route authenticates
// against Postgres instead of the in-memory store, closing the I-1 split-brain so
// account management AND login share one system of record. The plaintext password
// is dispatched to toee_workbench_admin.authenticate, which verifies the scrypt
// hash server-side and returns the public account (NEVER the hash) — so the hash
// stays pinned to the datastore. authenticate is pre-auth, so this uses dispatch
// (read-style, no actor required), not dispatchWrite. On success the session is
// issued exactly as handleLogin does (same body + signed cookie, ADR-0093); on a
// rejected credential the responses match the in-memory path (generic 401 for both
// bad password and unknown user — no enumeration; 403 for a disabled account;
// 423 once the ADR-0018 lockout window is open). As of 0.0.4 S08 the lockout
// ladder itself (5 failures -> 15 minutes, reset on success) is enforced by
// toee_workbench_admin.authenticate against the account row, so it is durable
// across a workbench restart and this handler only translates the verdict.
export async function handleLoginViaApi(
  req: Request,
  client: HermesApiClient,
  opts: { now: number; secret: string; secure: boolean },
): Promise<Response> {
  let raw: unknown;
  try {
    raw = await req.json();
  } catch {
    return problem(400, "invalid request body");
  }
  const body = parseLoginBody(raw);
  if (!body) return problem(400, "username and password are required");

  let account: ReturnType<typeof mapPublicAccount>;
  try {
    const data = (await client.dispatch("toee_workbench_admin", "authenticate", {
      username: body.username,
      password: body.password,
    })) as { account?: unknown };
    account = mapPublicAccount(data.account);
  } catch (err) {
    // Parity with the in-memory path: bad password and unknown user are one
    // generic 401 (the datastore raises the same `unauthenticated` for both, so
    // neither leaks which); a disabled account is 403. Anything else (transport,
    // unexpected) surfaces as a governed upstream failure on the ADR-0090 banner.
    if (err instanceof HermesApiError) {
      if (err.errorClass === "unauthenticated") {
        return problem(401, "invalid credentials");
      }
      if (err.errorClass === "policy_blocked") {
        return problem(403, "account disabled");
      }
      if (err.errorClass === "locked") {
        return problem(423, "account temporarily locked");
      }
    }
    return hermesErrorToProblem(err);
  }

  const token = await createSessionToken(
    {
      accountId: account.accountId,
      username: account.username,
      role: account.role,
      lastActivityAt: opts.now,
    },
    opts.secret,
  );

  return json(
    {
      user: {
        accountId: account.accountId,
        username: account.username,
        role: account.role,
      },
    },
    {
      headers: {
        "set-cookie": buildSessionCookie(token, {
          maxAgeSeconds: Math.floor(SESSION_IDLE_MS / 1000),
          secure: opts.secure,
        }),
      },
    },
  );
}

export async function handleSession(
  req: Request,
  deps: AuthDeps,
): Promise<Response> {
  const token = parseCookies(req.headers.get("cookie"))[SESSION_COOKIE_NAME];
  if (!token) return json({ authenticated: false });
  const session = await verifySessionToken(token, deps.secret);
  if (!session || isSessionExpired(session, deps.now)) {
    return json({ authenticated: false });
  }
  return json({
    authenticated: true,
    user: {
      accountId: session.accountId,
      username: session.username,
      role: session.role,
    },
  });
}

export function handleLogout(opts: { secure: boolean }): Response {
  return json(
    { ok: true },
    { headers: { "set-cookie": buildClearedSessionCookie(opts) } },
  );
}
