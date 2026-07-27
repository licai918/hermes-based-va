import { handleListAgentExperienceViaApi } from "@/lib/bff/admin/agent-experience";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-23 L6 Agent-experience admin list (0.0.3 S22). Dispatches over the Internal
// Copilot Profile API: toee_agent_experience is allowlisted for internal_copilot
// only. Read-only; S24 extends this into the Accept/Reject review queue.
export const GET = withSession((_req, { session }) =>
  handleListAgentExperienceViaApi(createCopilotApiClient(session)),
);
