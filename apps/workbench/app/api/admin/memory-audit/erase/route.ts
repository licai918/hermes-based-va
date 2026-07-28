import { handleEraseCustomerMemoryViaApi } from "@/lib/bff/admin/memory-audit";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-13 (0.0.5 S11, US7): the supervisor's whole-binding erase. Sibling of the
// per-slot clear route beside it, same shape and same reasons -- /api/admin/* is
// admin-gated by withSession (ADR-0093), case_id rides the query string so the
// route never reads the request body (there is no body), and the dispatch goes
// over the Internal Copilot Profile API because toee_customer_memory is
// allowlisted there and not on supervisor_admin.
export const POST = withSession((req, { session }) => {
  const caseId = new URL(req.url).searchParams.get("case_id") ?? "";
  if (!caseId) return problem(400, "case_id is required");
  return handleEraseCustomerMemoryViaApi(createCopilotApiClient(session), caseId);
});
