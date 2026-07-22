import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { handleClearPreferenceViaApi } from "@/lib/bff/copilot/preferences";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-20 (0.0.3 S20): the supervisor "Clear" action reuses the SAME governed
// clear_preference dispatch handleClearPreferenceViaApi already uses for the
// copilot correction flow -- no new write path, just a second (admin-gated,
// ADR-0093) entry point that attributes the audit to the signed-in
// supervisor/admin account instead of a rep. case_id rides the query string (not
// the JSON body) so this route never needs to read the request body twice.
export const POST = withSession((req, { session }) => {
  const caseId = new URL(req.url).searchParams.get("case_id") ?? "";
  if (!caseId) return problem(400, "case_id is required");
  return handleClearPreferenceViaApi(req, createCopilotApiClient(session), caseId);
});
