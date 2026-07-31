import { handleAnnotateInboxItemViaApi } from "@/lib/bff/admin/review-inbox";
import { readJsonBody } from "@/lib/bff/admin/deps";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-23 (0.0.5 S16): re-run copilot triage over ONE inbox item.
//
// POST with a body rather than a path shape, the sibling decide route's
// reasoning: an inbox id is only unique within its own store, so the kind has
// to travel with it.
//
// It is a POST and a dispatchWrite even though the result reads like a query,
// because it is not one: it spends a billed model completion and stores an
// annotation. Routing it as a GET would make it cacheable and retryable by
// anything between the browser and here.
export const POST = withSession(async (req, { session }) => {
  const body = await readJsonBody(req);
  if (!body) return problem(400, "a JSON body is required");
  const kind = typeof body.kind === "string" ? body.kind : "";
  const id = typeof body.id === "string" ? body.id : "";
  if (!id) return problem(400, "id is required");
  return handleAnnotateInboxItemViaApi(createCopilotApiClient(session), kind, id);
});
