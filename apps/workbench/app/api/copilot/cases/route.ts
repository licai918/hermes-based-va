import { handleListCases, handleListCasesViaApi } from "@/lib/bff/copilot/cases";
import { createCopilotDeps } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

// Node runtime: the copilot deps reach the session/account spine (node:crypto).
export const runtime = "nodejs";

export const GET = withSession((req, { session }) => {
  const deps = createCopilotDeps(session);
  // ADR-0141: when the Internal Copilot Profile API is configured, read the queue
  // over HTTP (deterministic tools:dispatch); otherwise fall back to the in-memory
  // store so local dev and tests run without the per-profile backend wired.
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  if (apiConfig) {
    // Thread the acting account (ADR-0141) so the dispatch audits attribute to it.
    const client = new HermesApiClient({
      ...apiConfig,
      actorAccountId: session.accountId,
    });
    return handleListCasesViaApi(req, client, deps);
  }
  return handleListCases(req, deps);
});
