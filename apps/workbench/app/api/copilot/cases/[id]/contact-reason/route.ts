import {
  handleContactReason,
  handleContactReasonViaApi,
} from "@/lib/bff/copilot/cases";
import { createCopilotDeps } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

export const POST = withSession((req, { session, params }) => {
  const caseId = params?.id ?? "";
  // ADR-0141: dispatch the governed contact-reason change over the Internal
  // Copilot Profile API when configured; otherwise fall back to the in-memory store.
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  if (apiConfig) {
    const client = new HermesApiClient({
      ...apiConfig,
      actorAccountId: session.accountId,
    });
    return handleContactReasonViaApi(req, client, caseId);
  }
  return handleContactReason(req, caseId, createCopilotDeps(session));
});
