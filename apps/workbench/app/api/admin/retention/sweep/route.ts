import { handleTriggerRetentionSweepViaApi } from "@/lib/bff/admin/retention";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

// FR-30 (0.0.3 S28): the governed retention-sweep trigger -- ages out
// customer_memory_slot rows per the ADR-0004/0116 class windows. /api/admin/*
// is already admin-gated by withSession (ADR-0093, lib/auth/access.ts's
// isAdminPath). Dispatches over the Internal Copilot Profile API, same as the
// sibling admin/retention GET route. The actor rides HermesApiClient's
// actorAccountId (from the signed-in session) into a governed dispatchWrite --
// never a client-supplied param.
export const POST = withSession((_req, { session }) => {
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  if (!apiConfig) {
    return problem(503, "Retention sweep backend is not configured", {
      errorClass: "configuration_missing",
    });
  }
  const client = new HermesApiClient({ ...apiConfig, actorAccountId: session.accountId });
  return handleTriggerRetentionSweepViaApi(client);
});
