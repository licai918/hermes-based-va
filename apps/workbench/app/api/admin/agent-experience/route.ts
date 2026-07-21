import { handleListAgentExperienceViaApi } from "@/lib/bff/admin/agent-experience";
import { json } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

// FR-23 L6 Agent-experience admin list (0.0.3 S22). /api/admin/* is already
// admin-gated by withSession (ADR-0093, lib/auth/access.ts's isAdminPath). See
// lib/bff/admin/agent-experience.ts's header comment for why this admin route
// dispatches over the Internal Copilot Profile API rather than the Supervisor
// Admin Profile API createAdminApiClient (deps.ts) uses elsewhere in this
// group. S24 extends this into the Accept/Reject review queue; this route is
// read-only.
export const GET = withSession((_req, { session }) => {
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  // API-path-only (mirrors admin/memory-audit): no in-memory-store concept for
  // Agent-experience, so an unconfigured backend degrades to an empty list
  // rather than a silent store no-op.
  if (!apiConfig) return json({ entries: [] });
  const client = new HermesApiClient({ ...apiConfig, actorAccountId: session.accountId });
  return handleListAgentExperienceViaApi(client);
});
