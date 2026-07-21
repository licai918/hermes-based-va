import { handleRejectExperienceViaApi } from "@/lib/bff/admin/agent-experience";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

// FR-24 (0.0.3 S24): the human confirm gate -- Reject. See the confirm route's
// header comment (same folder tree) for the full rationale; identical wiring,
// dispatches reject_experience instead.
export const POST = withSession((_req, { session, params }) => {
  const id = params?.id ?? "";
  if (!id) return problem(400, "id is required");
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  if (!apiConfig) {
    return problem(503, "Agent-experience backend is not configured", {
      errorClass: "configuration_missing",
    });
  }
  const client = new HermesApiClient({ ...apiConfig, actorAccountId: session.accountId });
  return handleRejectExperienceViaApi(client, id);
});
