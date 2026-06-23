// Server-side session reader for authenticated server components/layouts. Node
// runtime: reads the HttpOnly cookie via next/headers and the signing secret from
// env. Returns a live session or null (expired/invalid count as null) so callers
// redirect to /login — defense in depth behind the edge middleware.
import { cookies } from "next/headers";
import { getSessionSecret } from "./secret";
import {
  isSessionExpired,
  SESSION_COOKIE_NAME,
  verifySessionToken,
  type WorkbenchSession,
} from "./session";

export async function getServerSession(
  now: number = Date.now(),
): Promise<WorkbenchSession | null> {
  const store = await cookies();
  const token = store.get(SESSION_COOKIE_NAME)?.value;
  if (!token) return null;

  const session = await verifySessionToken(token, getSessionSecret());
  if (!session) return null;
  if (isSessionExpired(session, now)) return null;
  return session;
}
