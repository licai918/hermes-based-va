import { handleChat, handleChatViaApi } from "@/lib/bff/copilot/chat";
import { createCopilotDeps } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";
import { HermesAgentClient } from "@/lib/gateway/hermes-agent-client";
import { HermesApiClient } from "@/lib/gateway/hermes-api-client";
import { resolveProfileApiConfig } from "@/lib/gateway/hermes-api-config";

export const runtime = "nodejs";

export const POST = withSession((req, { session }) => {
  // ADR-0147 Slice 4 (#39): when the Internal Copilot Profile API is configured, run
  // the chat reply over the agent-turn (LLM) API — the agent client runs the turn,
  // the dispatch client does the 404 + channel pre-read. Otherwise fall back to the
  // in-memory stub so local dev and tests run without the per-profile backend wired
  // (same env pair as the drafts/case cutover — one server, two routes).
  const apiConfig = resolveProfileApiConfig(
    process.env.HERMES_COPILOT_API_URL,
    process.env.HERMES_COPILOT_API_TOKEN,
  );
  if (apiConfig) {
    const actorAccountId = session.accountId;
    const agent = new HermesAgentClient({ ...apiConfig, actorAccountId });
    const client = new HermesApiClient({ ...apiConfig, actorAccountId });
    return handleChatViaApi(req, agent, client);
  }
  return handleChat(req, createCopilotDeps(session));
});
