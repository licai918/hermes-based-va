// Pure access decision for the workbench middleware (ADR-0093 protection +
// route-derived gating, ADR-0018 idle timeout, ADR-0090 logged-out-on-expiry).
// EDGE-SAFE: imports only Edge-safe siblings + @toee/shared. The thin
// middleware.ts verifies the cookie signature and maps these decisions onto
// NextResponse, so all branching logic stays unit-testable here.
import { ROUTES } from "@toee/shared";
import { canAccess } from "./access";
import { isSessionExpired, type WorkbenchSession } from "./session";

// Re-sign the sliding session cookie only after this much inactivity, so a burst
// of requests does not re-issue the cookie on every single one.
export const REFRESH_THRESHOLD_MS = 60_000;

export type MiddlewareDecision = {
  action: "allow" | "redirect" | "unauthorized" | "forbidden";
  location?: string;
  // Re-issue the session cookie with a refreshed lastActivityAt (allow + authed).
  refreshCookie?: boolean;
  // Delete a stale/expired cookie on the way out.
  clearCookie?: boolean;
};

function isApiPath(pathname: string): boolean {
  return pathname === "/api" || pathname.startsWith("/api/");
}

// /login (page) and every /api/auth/* endpoint stay reachable without a session;
// the auth handlers return their own status codes.
function isPublicPath(pathname: string): boolean {
  return pathname === ROUTES.login || pathname.startsWith("/api/auth");
}

export function decideAccess(
  pathname: string,
  session: WorkbenchSession | null,
  now: number,
): MiddlewareDecision {
  const live = session && !isSessionExpired(session, now) ? session : null;
  const hadExpiredCookie = session !== null && live === null;

  if (isPublicPath(pathname)) {
    // Skip the login page for users who already hold a live session.
    if (pathname === ROUTES.login && live) {
      return { action: "redirect", location: ROUTES.copilot };
    }
    return { action: "allow" };
  }

  if (!live) {
    if (isApiPath(pathname)) {
      return { action: "unauthorized", clearCookie: hadExpiredCookie };
    }
    return {
      action: "redirect",
      location: ROUTES.login,
      clearCookie: hadExpiredCookie,
    };
  }

  if (!canAccess(live.role, pathname)) {
    if (isApiPath(pathname)) return { action: "forbidden" };
    return { action: "redirect", location: ROUTES.copilot };
  }

  return {
    action: "allow",
    refreshCookie: now - live.lastActivityAt > REFRESH_THRESHOLD_MS,
  };
}
