import { getAccountStore } from "@/lib/auth/account-store";
import { getSessionSecret } from "@/lib/auth/secret";
import { handleSession } from "@/lib/bff/auth-handlers";

export const runtime = "nodejs";

export function GET(req: Request): Promise<Response> {
  return handleSession(req, {
    store: getAccountStore(),
    now: Date.now(),
    secret: getSessionSecret(),
    secure: process.env.NODE_ENV === "production",
  });
}
