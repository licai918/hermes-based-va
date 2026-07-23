import { NextResponse } from "next/server";
import {
  clearedReconnectStateCookie,
  reconnectStateMatches,
  RECONNECT_STATE_COOKIE,
} from "@/lib/bff/admin/reconnect-state";
import { parseCookies, withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-25 (0.0.4 S17): the Composio OAuth reconnect callback. This route is
// EXTERNALLY REACHABLE (the provider redirects the admin's browser here), so its
// input is UNTRUSTED. It does NOTHING but verify the session-bound state and
// redirect -- no token is handled (Composio holds the credentials) and no other
// callback parameter is acted on.
//
// Fail closed: a state that does not exactly match the httpOnly cookie set at
// initiation is REFUSED -- we redirect back to the page with `reconnect=state_mismatch`
// and never signal success. The one-time state cookie is always cleared on the way
// out. ADMIN-ONLY via withSession (the path is under /api/admin/integrations), so a
// caller without a valid admin session is 401/403'd before this runs.
export const GET = withSession((req) => {
  const url = new URL(req.url);
  const queryState = url.searchParams.get("state");
  const key = url.searchParams.get("integration_key") ?? "";
  const cookieState = parseCookies(req.headers.get("cookie"))[RECONNECT_STATE_COOKIE];

  const ok = reconnectStateMatches(cookieState, queryState);

  const dest = new URL("/admin/integrations", url.origin);
  // On success carry the integration key so the page re-probes exactly that row; on a
  // mismatch carry the refusal marker so the page shows a fail-closed error instead.
  dest.searchParams.set("reconnect", ok ? key || "ok" : "state_mismatch");

  const res = NextResponse.redirect(dest);
  res.cookies.set(
    clearedReconnectStateCookie(process.env.NODE_ENV === "production"),
  );
  return res;
});
