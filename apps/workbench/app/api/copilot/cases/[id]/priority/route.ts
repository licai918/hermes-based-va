import { handlePriority, handlePriorityViaApi } from "@/lib/bff/copilot/cases";
import { createCopilotDeps } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

export const POST = withSession((req, { session, params }) => {
  const caseId = params?.id ?? "";
  const deps = createCopilotDeps(session);
  // ADR-0141: dispatch the governed priority change over the Internal Copilot
  // Profile API when configured; otherwise fall back to the in-memory store.
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  if (apiConfig) {
    const client = new HermesApiClient({
      ...apiConfig,
      actorAccountId: session.accountId,
    });
    return handlePriorityViaApi(req, client, caseId, deps);
  }
  return handlePriority(req, caseId, deps);
});
