import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { handleGetCorpusStatusViaApi } from "@/lib/bff/admin/knowledge";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// S11 (FR-6): corpus status has no in-memory fallback -- there is no corpus to
// fake -- so this route requires the per-profile Supervisor Admin API
// (HERMES_ADMIN_API_URL/TOKEN, ADR-0141) to be configured.
export const GET = withSession((_req, { session }) => {
  const client = createAdminApiClient(session);
  if (!client) return problem(503, "admin API not configured");
  return handleGetCorpusStatusViaApi(client);
});
