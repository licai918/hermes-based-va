import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { handleGetMemoryHubViaApi } from "@/lib/bff/admin/memory-hub";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-21 Memory Hub (0.0.5 S14): one aggregate read composing the five per-layer
// reads that already exist. /api/admin/* is admin-gated by withSession
// (ADR-0093). TWO clients, because the tools are allowlisted to different
// profiles: toee_knowledge_ops answers on the Supervisor Admin Profile (as
// admin/knowledge does), while toee_agent_experience / toee_semantic_lexicon /
// toee_retention / toee_metrics are internal_copilot-only. Read-only -- GET is
// the only verb, and the handler never calls dispatchWrite.
export const GET = withSession((_req, { session }) =>
  handleGetMemoryHubViaApi(createCopilotApiClient(session), createAdminApiClient(session)),
);
