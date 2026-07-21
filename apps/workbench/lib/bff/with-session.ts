// Route-handler auth guard for the workbench BFF. Node runtime (reads the session
// secret from env via getSessionSecret). Wraps Next.js App Router handlers,
// enforcing: valid signed session cookie (ADR-0093), idle timeout (ADR-0018), and
// route-derived role gating (ADR-0093/0077/0078).
import { canAccess } from "../auth/access";
import { getSessionSecret } from "../auth/secret";
import {
  isSessionExpired,
  SESSION_COOKIE_NAME,
  verifySessionToken,
  type WorkbenchSession,
} from "../auth/session";
import { problem } from "./respond";
import { hermesErrorToProblem } from "../gateway/hermes-error";

// Minimal cookie-header parser so the guard stays unit-testable with a plain
// `Request` (no dependency on next/headers).
export function parseCookies(header: string | null): Record<string, string> {
  const cookies: Record<string, string> = {};
  if (!header) return cookies;
  for (const segment of header.split(";")) {
    const eq = segment.indexOf("=");
    if (eq === -1) continue;
    const name = segment.slice(0, eq).trim();
    if (!name) continue;
    let value = segment.slice(eq + 1).trim();
    try {
      value = decodeURIComponent(value);
    } catch {
      // Not valid percent-encoding — keep the raw value.
    }
    cookies[name] = value;
  }
  return cookies;
}

export type WithSessionContext = {
  session: WorkbenchSession;
  params?: Record<string, string>;
};

export type SessionHandler = (
  req: Request,
  ctx: WithSessionContext,
) => Promise<Response> | Response;

// Next 16 passes route params as a Promise; accept either shape.
type NextRouteContext = {
  params?: Promise<Record<string, string>> | Record<string, string>;
};

export type WithSessionOptions = Record<string, never>;

export function withSession(
  handler: SessionHandler,
  options?: WithSessionOptions,
): (req: Request, routeCtx?: NextRouteContext) => Promise<Response> {
  void options; // reserved for future per-route configuration
  return async (req, routeCtx) => {
    const token = parseCookies(req.headers.get("cookie"))[SESSION_COOKIE_NAME];
    if (!token) return problem(401, "missing session");

    const session = await verifySessionToken(token, getSessionSecret());
    if (!session) return problem(401, "invalid session");

    if (isSessionExpired(session, Date.now())) {
      return problem(401, "session expired");
    }

    const pathname = new URL(req.url).pathname;
    if (!canAccess(session.role, pathname)) return problem(403, "forbidden");

    const params = routeCtx?.params ? await routeCtx.params : undefined;
    try {
      return await handler(req, { session, params });
    } catch (err) {
      // Last-resort governed fallback: a route handler's SYNCHRONOUS setup runs
      // outside its own try/catch (e.g. `new HermesApiClient(...)`, config
      // resolution), and an async rejection its inner catch didn't cover would
      // otherwise leak a bare Next.js 500 to the error banner. Map ANY throw
      // through the same hermesErrorToProblem the BFF handlers use, so every
      // withSession route surfaces a governed (ADR-0020-safe) error Response
      // instead of an opaque 500. HermesApiError keeps its class/status; any
      // other throw becomes a 502 "service unavailable".
      return hermesErrorToProblem(err);
    }
  };
}
