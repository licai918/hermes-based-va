import { NextResponse } from "next/server";
import { handleInitiateReconnectViaApi } from "@/lib/bff/admin/integrations";
import { createAdminApiClient, readJsonBody } from "@/lib/bff/admin/deps";
import {
  newReconnectState,
  reconnectStateCookie,
} from "@/lib/bff/admin/reconnect-state";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-25 (0.0.4 S17): start a Composio OAuth reconnect. ADMIN-ONLY (withSession ->
// canAccess -> requiresAdmin, since the path is under /api/admin/integrations). The
// acting admin rides createAdminApiClient's actorAccountId (ADR-0148) -- the body
// carries only the integration key, and an actor in the body is never read.
//
// The callback_url is built HERE from this server's own origin plus a freshly minted
// session-bound state; it is NOT client-supplied. On success we set the state as an
// httpOnly cookie and return the provider redirect URL for the browser to navigate to.
// A fail-closed backend (owner-blocked / wrong SDK guess) returns an error with no
// cookie and no URL, so the client never navigates to a fabricated link.
export const POST = withSession(async (req, { session }) => {
  const body = await readJsonBody(req);
  const integrationKey = body?.integrationKey;
  const key = typeof integrationKey === "string" ? integrationKey : "";

  const origin = new URL(req.url).origin;
  const state = newReconnectState();
  const callbackUrl =
    `${origin}/api/admin/integrations/callback` +
    `?state=${encodeURIComponent(state)}` +
    `&integration_key=${encodeURIComponent(key)}`;

  const client = createAdminApiClient(session);
  const res = await handleInitiateReconnectViaApi(client, integrationKey, callbackUrl);

  // Only bind state to a successful link generation -- an error response carries no
  // usable redirect, so it must not arm a callback either.
  if (res.status !== 200) return res;

  const out = new NextResponse(await res.text(), {
    status: res.status,
    headers: res.headers,
  });
  out.cookies.set(reconnectStateCookie(state, process.env.NODE_ENV === "production"));
  return out;
});
