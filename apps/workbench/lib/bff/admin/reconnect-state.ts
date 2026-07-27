// OAuth reconnect CSRF-state binding (0.0.4 S17, FR-25).
//
// The Composio OAuth reconnect (initiate_reconnect) sends the admin's browser to the
// provider and back to our callback route. That callback is EXTERNALLY REACHABLE, so
// its input is untrusted: without a bound `state` an attacker could forge a callback
// that lands the page as if a reconnect completed. We use the standard OAuth state
// pattern -- a random value round-tripped through the provider and compared on return
// against an httpOnly cookie set at initiation:
//
//   initiate -> mint state, set httpOnly cookie, append ?state=<state> to callback_url
//   provider round-trips the state
//   callback -> compare query state to the cookie; MISMATCH => refuse (fail closed)
//
// The cookie is httpOnly (JS cannot read/forge it) and sameSite=lax (so it survives
// the top-level GET redirect back from the provider -- strict would drop it). Bound to
// the admin session by construction: only a signed-in admin's browser holds it, and
// the callback route itself is admin-only (withSession). No token is ever handled here
// -- Composio holds the credentials; state is a random nonce, not a secret.
//
// ponytail: state is a random httpOnly cookie compared on return -- the standard OAuth
// CSRF defense. If multiple admins ever share one browser session and that becomes a
// concern, HMAC the state with the session accountId; not worth the code today.
import { randomUUID } from "node:crypto";

export const RECONNECT_STATE_COOKIE = "integrations_reconnect_state";

// Scoped to the reconnect routes so it never rides other admin requests. 10 min is
// plenty for an OAuth round-trip and bounds how long a stale nonce lingers.
const COOKIE_PATH = "/api/admin/integrations";
const MAX_AGE_SECONDS = 600;

export function newReconnectState(): string {
  return randomUUID();
}

export interface CookieAttributes {
  name: string;
  value: string;
  httpOnly: boolean;
  sameSite: "lax";
  path: string;
  maxAge: number;
  secure: boolean;
}

export function reconnectStateCookie(state: string, secure: boolean): CookieAttributes {
  return {
    name: RECONNECT_STATE_COOKIE,
    value: state,
    httpOnly: true,
    sameSite: "lax",
    path: COOKIE_PATH,
    maxAge: MAX_AGE_SECONDS,
    secure,
  };
}

export function clearedReconnectStateCookie(secure: boolean): CookieAttributes {
  return { ...reconnectStateCookie("", secure), maxAge: 0 };
}

// The one security decision: a reconnect callback is accepted ONLY when a non-empty
// state cookie exactly matches the non-empty state query param. A missing cookie, a
// missing query value, or any mismatch is refused -- fail closed, never a partial pass.
export function reconnectStateMatches(
  cookieState: string | undefined,
  queryState: string | null,
): boolean {
  if (!cookieState || !queryState) return false;
  return cookieState === queryState;
}
