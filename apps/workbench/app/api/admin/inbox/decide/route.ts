import { handleDecideInboxItemViaApi } from "@/lib/bff/admin/review-inbox";
import { readJsonBody } from "@/lib/bff/admin/deps";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-22 (0.0.5 S15): one inbox decision, routed to the layer that owns it.
//
// POST with a body rather than the sibling consoles' `/[id]/[decision]` path
// shape, because an inbox id is only unique WITHIN its store -- the same id
// string could name an agent_experience row and a review_item, and the routing
// table keys on (kind, decision). Putting the kind in the path would make it a
// third path segment nobody can validate independently.
//
// The actor rides the client's actorAccountId (from the signed-in session) into
// a governed dispatchWrite -- never a client-supplied param. A decision the kind
// does not offer is a 400 from the handler, before any dispatch.
export const POST = withSession(async (req, { session }) => {
  const body = await readJsonBody(req);
  if (!body) return problem(400, "a JSON body is required");
  const kind = typeof body.kind === "string" ? body.kind : "";
  const id = typeof body.id === "string" ? body.id : "";
  const decision = typeof body.decision === "string" ? body.decision : "";
  if (!id) return problem(400, "id is required");
  return handleDecideInboxItemViaApi(
    createCopilotApiClient(session),
    kind,
    id,
    decision,
  );
});
