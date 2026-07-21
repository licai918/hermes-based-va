import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { handleTriggerReingestViaApi } from "@/lib/bff/admin/knowledge";
import { problem } from "@/lib/bff/respond";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// 0.0.4 S04 (FR-11): queue a knowledge corpus re-ingest. Replaces 0.0.3 S11's
// display-only panel stub (it printed a CLI command). /api/admin/* is already
// admin-gated by withSession (ADR-0093); the acting supervisor rides
// createAdminApiClient's actorAccountId into a governed dispatchWrite, so a
// corpus wipe-and-reload can never land unattributed.
export const POST = withSession((_req, { session }) => {
  const client = createAdminApiClient(session);
  if (!client) return problem(503, "admin API not configured");
  return handleTriggerReingestViaApi(client);
});
