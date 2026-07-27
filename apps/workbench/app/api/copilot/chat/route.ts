import { handleChatViaApi } from "@/lib/bff/copilot/chat";
import {
  createCopilotAgentClient,
  createCopilotApiClient,
} from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// ADR-0147 Slice 4 (#39): the chat reply is a genuine unbound internal_copilot
// agent turn over the agent-turn (LLM) API -- the agent client runs the turn, the
// dispatch client does the 404 + channel pre-read. 0.0.4 S09 deleted the
// deterministic in-memory stub; this is the only chat path.
export const POST = withSession((req, { session }) =>
  handleChatViaApi(req, createCopilotAgentClient(session), createCopilotApiClient(session)),
);
