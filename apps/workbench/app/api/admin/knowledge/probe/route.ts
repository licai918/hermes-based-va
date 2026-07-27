import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { handleProbeQueryViaApi } from "@/lib/bff/admin/knowledge";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// The retrieval probe dispatches toee_knowledge_search.search_public_site, hitting
// the real retriever when the dispatch server runs with KNOWLEDGE_BACKEND=retriever.
export const POST = withSession((req, { session }) =>
  handleProbeQueryViaApi(req, createAdminApiClient(session)),
);
