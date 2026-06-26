import { getAccountStore } from "@/lib/auth/account-store";
import { getSessionSecret } from "@/lib/auth/secret";
import { handleLogin, handleLoginViaApi } from "@/lib/bff/auth-handlers";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

// Node runtime: login verifies scrypt hashes (node:crypto) via the account store,
// or dispatches to the per-profile API which verifies them server-side (ADR-0144).
export const runtime = "nodejs";

export function POST(req: Request): Promise<Response> {
  const secret = getSessionSecret();
  const secure = process.env.NODE_ENV === "production";
  const now = Date.now();

  // When the admin per-profile API is configured (ADR-0141), authenticate against
  // Postgres so login and account management share one system of record, closing
  // the I-1 split-brain (ADR-0144). Login is pre-auth, so the client carries no
  // actor — authenticate uses dispatch (read-style), not a governed write.
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_ADMIN_API_URL,
    process.env.HERMES_ADMIN_API_TOKEN,
  );
  if (apiConfig) {
    return handleLoginViaApi(req, new HermesApiClient(apiConfig), {
      now,
      secret,
      secure,
    });
  }

  return handleLogin(req, { store: getAccountStore(), now, secret, secure });
}
