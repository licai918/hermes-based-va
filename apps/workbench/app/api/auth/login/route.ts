import { getSessionSecret } from "@/lib/auth/secret";
import { handleLoginViaApi } from "@/lib/bff/auth-handlers";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { requireProfileApiConfig } from "@/lib/gateway/hermes-api-config";

// Node runtime: the session spine signs cookies with node:crypto. Credentials are
// verified server-side by toee_workbench_admin.authenticate (ADR-0144), which also
// owns the ADR-0018 lockout ladder (0.0.4 S08) -- login and account management
// share one system of record. Login is pre-auth, so the client carries no actor:
// authenticate uses dispatch (read-style), not a governed write.
export const runtime = "nodejs";

export function POST(req: Request): Promise<Response> {
  return handleLoginViaApi(req, new HermesApiClient(requireProfileApiConfig("admin")), {
    now: Date.now(),
    secret: getSessionSecret(),
    secure: process.env.NODE_ENV === "production",
  });
}
