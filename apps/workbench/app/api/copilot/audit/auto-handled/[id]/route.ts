import {
  handleGetAutoHandled,
  handleGetAutoHandledViaApi,
} from "@/lib/bff/copilot/audit";
import { createCopilotDeps } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

export const GET = withSession((_req, { session, params }) => {
  const recordId = params?.id ?? "";
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  if (apiConfig) {
    const client = new HermesApiClient({
      ...apiConfig,
      actorAccountId: session.accountId,
    });
    return handleGetAutoHandledViaApi(client, recordId);
  }
  return handleGetAutoHandled(recordId, createCopilotDeps(session));
});
