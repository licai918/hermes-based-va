import {
  createCopilotAgentClient,
  createCopilotApiClient,
} from "@/lib/bff/copilot/deps";
import { handleDraftViaApi } from "@/lib/bff/copilot/drafts";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// ADR-0147 Slice 2: the draft is a genuine unbound internal_copilot agent turn over
// the agent-turn (LLM) API -- the agent client runs the turn, the dispatch client
// does the 404 pre-read. The draft_generated audit is written server-side (#47).
export const POST = withSession((req, { session }) =>
  handleDraftViaApi(
    req,
    createCopilotAgentClient(session),
    createCopilotApiClient(session),
    "draft_internal_note",
  ),
);
