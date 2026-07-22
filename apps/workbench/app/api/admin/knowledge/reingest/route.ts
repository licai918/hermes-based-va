import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { handleTriggerReingestViaApi } from "@/lib/bff/admin/knowledge";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// 0.0.4 S04 (FR-11): queue a knowledge corpus re-ingest. The acting supervisor
// rides createAdminApiClient's actorAccountId into a governed dispatchWrite, so a
// corpus wipe-and-reload can never land unattributed.
export const POST = withSession((_req, { session }) =>
  handleTriggerReingestViaApi(createAdminApiClient(session)),
);
