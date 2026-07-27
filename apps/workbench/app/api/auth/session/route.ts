import { getSessionSecret } from "@/lib/auth/secret";
import { handleSession } from "@/lib/bff/auth-handlers";

export const runtime = "nodejs";

// Reads the signed cookie only -- no account lookup, so no backend call.
export function GET(req: Request): Promise<Response> {
  return handleSession(req, { now: Date.now(), secret: getSessionSecret() });
}
