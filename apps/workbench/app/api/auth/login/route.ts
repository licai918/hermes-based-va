import { getAccountStore } from "@/lib/auth/account-store";
import { getSessionSecret } from "@/lib/auth/secret";
import { handleLogin } from "@/lib/bff/auth-handlers";

// Node runtime: login verifies scrypt hashes (node:crypto) via the account store.
export const runtime = "nodejs";

export function POST(req: Request): Promise<Response> {
  return handleLogin(req, {
    store: getAccountStore(),
    now: Date.now(),
    secret: getSessionSecret(),
    secure: process.env.NODE_ENV === "production",
  });
}
