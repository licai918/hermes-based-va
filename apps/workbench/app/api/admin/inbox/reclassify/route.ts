import { handleReclassifyInboxItemViaApi } from "@/lib/bff/admin/review-inbox";
import { readJsonBody } from "@/lib/bff/admin/deps";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-22 (0.0.5 S15): Re-classify -- move a mis-filed proposal to the other
// layer's queue instead of reject-and-retype. ONE governed action on the Hermes
// side rejects the source and proposes the target in one transaction, audits
// both, and preserves the evidence. The actor rides the session into a governed
// dispatchWrite; a write with no resolvable actor is policy_blocked on the
// Hermes side too (ADR-0148).
export const POST = withSession(async (req, { session }) => {
  const body = await readJsonBody(req);
  if (!body) return problem(400, "a JSON body is required");
  const text = (key: string): string | undefined =>
    typeof body[key] === "string" ? (body[key] as string) : undefined;
  return handleReclassifyInboxItemViaApi(createCopilotApiClient(session), {
    sourceKind: text("sourceKind"),
    id: text("id"),
    domain: text("domain"),
    entryKind: text("entryKind"),
    surfaceForm: text("surfaceForm"),
    canonicalForm: text("canonicalForm"),
  });
});
