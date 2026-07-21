import { handleDismissProposalViaApi } from "@/lib/bff/copilot/preferences";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

// API-path-only (PAC-4/S17, S15): see ../route.ts -- no in-memory-store fallback.
export const POST = withSession((req, { session, params }) => {
  const caseId = params?.id ?? "";
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  if (!apiConfig) {
    return problem(503, "Customer Memory backend is not configured", {
      errorClass: "configuration_missing",
    });
  }
  const client = new HermesApiClient({
    ...apiConfig,
    actorAccountId: session.accountId,
  });
  return handleDismissProposalViaApi(req, client, caseId);
});
