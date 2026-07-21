import { handleConfirmExperienceViaApi } from "@/lib/bff/admin/agent-experience";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

// FR-24 (0.0.3 S24): the human confirm gate -- Accept. /api/admin/* is already
// admin-gated by withSession (ADR-0093, lib/auth/access.ts's isAdminPath).
// Dispatches over the Internal Copilot Profile API, same as the sibling
// agent-experience routes (see lib/bff/admin/agent-experience.ts's header
// comment for why): toee_agent_experience is allowlisted for internal_copilot
// only. The actor rides HermesApiClient's actorAccountId (from the signed-in
// session) into a governed dispatchWrite -- never a client-supplied param.
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
  return handleConfirmExperienceViaApi(client, id);
});
