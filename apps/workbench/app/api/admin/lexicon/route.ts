import {
  handleAddLexiconViaApi,
  handleListLexiconViaApi,
} from "@/lib/bff/admin/semantic-lexicon";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-1/FR-8 L7 Semantic Lexicon admin list (0.0.5 S01/S02). Dispatches over the
// Internal Copilot Profile API: toee_semantic_lexicon is allowlisted for
// internal_copilot only. `status`/`domain` are the queue filters S02 added to
// the ONE read action rather than shipping a second one.
export const GET = withSession((req, { session }) => {
  const url = new URL(req.url);
  return handleListLexiconViaApi(createCopilotApiClient(session), {
    status: url.searchParams.get("status") ?? undefined,
    domain: url.searchParams.get("domain") ?? undefined,
  });
});

// FR-8/US1: the admin's own entry -- lands `confirmed` + `admin_manual`, live
// with no deploy. The actor rides the client's actorAccountId (from the signed-in
// session) into a governed dispatchWrite; a write with no resolvable actor is
// policy_blocked on the Hermes side too (D20).
export const POST = withSession(async (req, { session }) => {
  const body = (await req.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body || typeof body !== "object") return problem(400, "a JSON body is required");
  return handleAddLexiconViaApi(createCopilotApiClient(session), {
    domain: typeof body.domain === "string" ? body.domain : undefined,
    entryKind: typeof body.entryKind === "string" ? body.entryKind : undefined,
    surfaceForm: typeof body.surfaceForm === "string" ? body.surfaceForm : undefined,
    canonicalForm:
      typeof body.canonicalForm === "string" ? body.canonicalForm : undefined,
    evidence: typeof body.evidence === "string" ? body.evidence : undefined,
  });
});
