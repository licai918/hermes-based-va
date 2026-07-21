import { EMPTY_AGGREGATE_METRICS, handleGetAggregateMetricsViaApi } from "@/lib/bff/admin/metrics";
import { json } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

// FR-28 aggregate-metrics admin panel (0.0.3 S26). /api/admin/* is already
// admin-gated by withSession (ADR-0093, lib/auth/access.ts's isAdminPath). See
// lib/bff/admin/metrics.ts's header comment for why this admin route
// dispatches over the Internal Copilot Profile API rather than the Supervisor
// Admin Profile API createAdminApiClient (deps.ts) uses elsewhere in this
// group -- same precedent as admin/memory-audit and admin/agent-experience.
// Read-only.
export const GET = withSession((_req, { session }) => {
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  // API-path-only (mirrors admin/agent-experience): no in-memory-store concept
  // for aggregate metrics, so an unconfigured backend degrades to the honestly
  // zeroed/labeled shape rather than a silent store no-op.
  if (!apiConfig) return json(EMPTY_AGGREGATE_METRICS);
  const client = new HermesApiClient({ ...apiConfig, actorAccountId: session.accountId });
  return handleGetAggregateMetricsViaApi(client);
});
