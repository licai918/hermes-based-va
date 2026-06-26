// Workbench edge middleware (ADR-0092/0093). Verifies the signed session cookie
// at the edge (session.ts is Web-Crypto-only), then maps the pure decideAccess
// decision onto NextResponse: redirect unauthenticated pages to /login, 401/403
// JSON for the BFF, refresh the sliding session cookie, and clear stale cookies.
// All branching lives in lib/auth/middleware-decision.ts; this file is glue.
import { NextResponse, type NextRequest } from "next/server";
import { decideAccess } from "@/lib/auth/middleware-decision";
import {
  createSessionToken,
  SESSION_COOKIE_NAME,
  SESSION_IDLE_MS,
  verifySessionToken,
  type WorkbenchSession,
} from "@/lib/auth/session";
import { resolveSessionSecret } from "@/lib/auth/session-secret";

// Run on everything except Next internals and static assets; the decision
// function applies the /login + /api/auth public exceptions.
export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};

function clearSessionCookie(res: NextResponse, secure: boolean): void {
  res.cookies.set({
    name: SESSION_COOKIE_NAME,
    value: "",
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 0,
    secure,
  });
}

function setSessionCookie(
  res: NextResponse,
  token: string,
  secure: boolean,
): void {
  res.cookies.set({
    name: SESSION_COOKIE_NAME,
    value: token,
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: Math.floor(SESSION_IDLE_MS / 1000),
    secure,
  });
}

export async function middleware(req: NextRequest): Promise<NextResponse> {
  const { pathname } = req.nextUrl;
  const secret = resolveSessionSecret(process.env.WORKBENCH_SESSION_SECRET);
  const token = req.cookies.get(SESSION_COOKIE_NAME)?.value;
  const session: WorkbenchSession | null = token
    ? await verifySessionToken(token, secret)
    : null;
  const now = Date.now();
  const secure = process.env.NODE_ENV === "production";

  const decision = decideAccess(pathname, session, now);

  switch (decision.action) {
    case "redirect": {
      const url = req.nextUrl.clone();
      url.pathname = decision.location ?? "/login";
      url.search = "";
      const res = NextResponse.redirect(url);
      if (decision.clearCookie) clearSessionCookie(res, secure);
      return res;
    }
    case "unauthorized": {
      const res = NextResponse.json({ error: "missing session" }, { status: 401 });
      if (decision.clearCookie) clearSessionCookie(res, secure);
      return res;
    }
    case "forbidden":
      return NextResponse.json({ error: "forbidden" }, { status: 403 });
    default: {
      const res = NextResponse.next();
      if (decision.refreshCookie && session) {
        const refreshed = await createSessionToken(
          { ...session, lastActivityAt: now },
          secret,
        );
        setSessionCookie(res, refreshed, secure);
      }
      return res;
    }
  }
}
