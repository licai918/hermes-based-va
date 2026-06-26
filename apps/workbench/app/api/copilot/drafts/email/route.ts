import { createCopilotDeps } from "@/lib/bff/copilot/deps";
import { handleDraft, handleDraftViaApi } from "@/lib/bff/copilot/drafts";
import { withSession } from "@/lib/bff/with-session";
import { HermesAgentClient } from "@/lib/gateway/hermes-agent-client";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

export const POST = withSession((req, { session }) => {
  const deps = createCopilotDeps(session);
  // ADR-0147 Slice 2: when the Internal Copilot Profile API is configured, generate
  // the email draft over the agent-turn (LLM) API — the agent client runs the turn,
  // the dispatch client does the 404 pre-read. Otherwise fall back to the in-memory
  // mock so local dev and tests run without the per-profile backend wired.
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  if (apiConfig) {
    const actorAccountId = session.accountId;
    const agent = new HermesAgentClient({ ...apiConfig, actorAccountId });
    const client = new HermesApiClient({ ...apiConfig, actorAccountId });
    return handleDraftViaApi(req, agent, client, deps, "draft_email");
  }
  return handleDraft(req, deps, "draft_email");
});
