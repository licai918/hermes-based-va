import { handleDraftLexiconViaApi } from "@/lib/bff/admin/semantic-lexicon";
import { createCopilotAgentClient, readJsonBody } from "@/lib/bff/copilot/deps";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-24 (0.0.5 S17): draft a lexicon entry from an administrator's own sentence
// so the S02 add form opens pre-filled.
//
// The AGENT client, not the deterministic one: this is a model call, and it is
// mounted on the Internal Copilot Profile server beside `agent:turn` for the
// same reason the lexicon read/write routes in this folder dispatch there --
// `toee_semantic_lexicon` and the LLM seam both live on internal_copilot.
//
// It writes nothing. The governed write is the admin's own Add, unchanged.
export const POST = withSession(async (req, { session }) => {
  const body = await readJsonBody(req);
  const text = typeof body?.text === "string" ? body.text : "";
  if (!text.trim()) return problem(400, "text is required");
  return handleDraftLexiconViaApi(createCopilotAgentClient(session), text);
});
