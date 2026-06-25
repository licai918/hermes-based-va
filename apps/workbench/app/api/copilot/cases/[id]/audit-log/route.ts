import {
  handleGetAuditLog,
  handleGetAuditLogViaApi,
} from "@/lib/bff/copilot/cases";
import { createCopilotDeps } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

export const GET = withSession((_req, { session, params }) => {
  const caseId = params?.id ?? "";
  // ADR-0141: read the case audit log over the Internal Copilot Profile dispatch
  // when configured; otherwise fall back to the in-memory store for local/test.
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  if (apiConfig) {
    return handleGetAuditLogViaApi(new HermesApiClient(apiConfig), caseId);
  }
  return handleGetAuditLog(caseId, createCopilotDeps(session));
});
