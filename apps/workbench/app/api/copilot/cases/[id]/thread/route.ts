import { handleGetThread, handleGetThreadViaApi } from "@/lib/bff/copilot/cases";
import { createCopilotDeps } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

export const GET = withSession((_req, { session, params }) => {
  const caseId = params?.id ?? "";
  // ADR-0141: read the Case Thread Context over the Internal Copilot Profile
  // dispatch when its API is configured; otherwise fall back to the in-memory
  // store for local/test. The API path also writes the case_view audit (ADR-0042).
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  if (apiConfig) {
    // Thread the acting account (ADR-0141) so the case_view audit attributes to it.
    const client = new HermesApiClient({
      ...apiConfig,
      actorAccountId: session.accountId,
    });
    return handleGetThreadViaApi(client, caseId);
  }
  return handleGetThread(caseId, createCopilotDeps(session));
});
