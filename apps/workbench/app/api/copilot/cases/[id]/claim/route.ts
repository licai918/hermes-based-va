import { handleClaim, handleClaimViaApi } from "@/lib/bff/copilot/cases";
import { createCopilotDeps } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

export const POST = withSession((_req, { session, params }) => {
  const caseId = params?.id ?? "";
  const deps = createCopilotDeps(session);
  // ADR-0141: dispatch the governed claim over the Internal Copilot Profile API
  // when configured (actor-attributed audit); otherwise use the in-memory store.
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  if (apiConfig) {
    const client = new HermesApiClient({
      ...apiConfig,
      actorAccountId: session.accountId,
    });
    return handleClaimViaApi(client, caseId, deps);
  }
  return handleClaim(caseId, deps);
});
