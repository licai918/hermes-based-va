import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { handleProbeQueryViaApi } from "@/lib/bff/admin/knowledge";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// S11 (FR-6, S08's re-scoped layer-② evidence): the retrieval probe dispatches
// toee_knowledge_search.search_public_site through the admin profile API, so it
// requires the per-profile API to be configured (same as corpus-status).
export const POST = withSession((req, { session }) => {
  const client = createAdminApiClient(session);
  if (!client) return problem(503, "admin API not configured");
  return handleProbeQueryViaApi(req, client);
});
