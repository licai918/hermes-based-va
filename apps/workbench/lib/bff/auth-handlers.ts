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
import { buildClearedSessionCookie, buildSessionCookie } from "./cookie";
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
