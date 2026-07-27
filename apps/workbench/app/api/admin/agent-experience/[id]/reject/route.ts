import { handleRejectExperienceViaApi } from "@/lib/bff/admin/agent-experience";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-24 (0.0.3 S24): the human confirm gate -- Reject. Dispatches over the Internal
// Copilot Profile API (toee_agent_experience is allowlisted for internal_copilot
// only). The actor rides the client's actorAccountId (from the signed-in session)
// into a governed dispatchWrite -- never a client-supplied param.
export const POST = withSession((_req, { session, params }) => {
  const id = params?.id ?? "";
  if (!id) return problem(400, "id is required");
  return handleRejectExperienceViaApi(createCopilotApiClient(session), id);
});
