import { NEVER_RUN_RETENTION_STATUS, handleGetRetentionStatusViaApi } from "@/lib/bff/admin/retention";
import { json } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

// FR-30 (0.0.3 S28): Customer Memory retention sweep admin panel -- last run +
// per-class counts. /api/admin/* is already admin-gated by withSession
// (ADR-0093, lib/auth/access.ts's isAdminPath). Dispatches over the Internal
// Copilot Profile API rather than the Supervisor Admin Profile API
// createAdminApiClient (deps.ts) uses elsewhere in this group -- same
// precedent as admin/metrics and admin/agent-experience. Read-only.
export const GET = withSession((_req, { session }) => {
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  // API-path-only (mirrors admin/metrics): no in-memory-store concept for the
  // retention sweep, so an unconfigured backend degrades to the honest
  // "never run" shape rather than a silent store no-op.
  if (!apiConfig) return json(NEVER_RUN_RETENTION_STATUS);
  const client = new HermesApiClient({ ...apiConfig, actorAccountId: session.accountId });
  return handleGetRetentionStatusViaApi(client);
});
