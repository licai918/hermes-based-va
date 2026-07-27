import { handleGetMemoryAuditViaApi } from "@/lib/bff/admin/memory-audit";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-20 supervisor memory audit view (0.0.3 S20). /api/admin/* is already
// admin-gated by withSession (ADR-0093, lib/auth/access.ts's isAdminPath). See
// lib/bff/admin/memory-audit.ts's header comment for why this admin route
// dispatches over the Internal Copilot Profile API rather than the Supervisor
// Admin Profile API the rest of this group uses.
export const GET = withSession((req, { session }) => {
  const caseId = new URL(req.url).searchParams.get("case_id") ?? "";
  if (!caseId) return problem(400, "case_id is required");
  return handleGetMemoryAuditViaApi(createCopilotApiClient(session), caseId);
});
