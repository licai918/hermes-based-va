import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { handleUpsertPreferenceViaApi } from "@/lib/bff/copilot/preferences";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-25 (0.0.5 S17): the supervisor's prefilled L4 correction, landing through
// the SAME governed `upsert_preference` dispatch the copilot correction flow
// already uses -- no new write path, just a second (admin-gated, ADR-0093) entry
// point that attributes the write to the signed-in supervisor. `source` stays
// framework-derived (`employee_confirmed`); it is not, and cannot be, a param.
//
// Sibling of ../clear/route.ts, down to `case_id` riding the query string so the
// route never reads the request body twice.
export const POST = withSession((req, { session }) => {
  const caseId = new URL(req.url).searchParams.get("case_id") ?? "";
  if (!caseId) return problem(400, "case_id is required");
  return handleUpsertPreferenceViaApi(req, createCopilotApiClient(session), caseId);
});
