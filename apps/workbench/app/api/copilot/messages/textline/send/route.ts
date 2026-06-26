import { createCopilotDeps } from "@/lib/bff/copilot/deps";
import { handleTextlineSend, handleTextlineSendViaApi } from "@/lib/bff/copilot/messages";
import { withSession } from "@/lib/bff/with-session";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

export const POST = withSession((req, { session }) => {
  const deps = createCopilotDeps(session);
  // ADR-0141 / #42: when the Internal Copilot Profile API is configured, run the
  // governed Textline send over tools:dispatch (server-side mirror + audit).
  // Otherwise fall back to the in-memory store path.
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  if (apiConfig) {
    const client = new HermesApiClient({
      ...apiConfig,
      actorAccountId: session.accountId,
    });
    return handleTextlineSendViaApi(req, client, deps);
  }
  return handleTextlineSend(req, deps);
});
