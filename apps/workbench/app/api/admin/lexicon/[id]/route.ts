import { handleEditLexiconViaApi } from "@/lib/bff/admin/semantic-lexicon";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// D7 (0.0.5 S02): edit is an IN-PLACE update and the entry id is stable, so this
// is a PATCH on the entry itself -- not a delete-and-recreate. An omitted field
// means "leave unchanged"; the server requires at least one.
export const PATCH = withSession(async (req, { session, params }) => {
  const id = params?.id ?? "";
  if (!id) return problem(400, "id is required");
  const body = (await req.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body || typeof body !== "object") return problem(400, "a JSON body is required");
  return handleEditLexiconViaApi(createCopilotApiClient(session), id, {
    surfaceForm: typeof body.surfaceForm === "string" ? body.surfaceForm : undefined,
    canonicalForm:
      typeof body.canonicalForm === "string" ? body.canonicalForm : undefined,
  });
});
