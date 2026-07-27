import { handleReplayJobViaApi } from "@/lib/bff/admin/dead-letter";
import { createAdminApiClient, readJsonBody } from "@/lib/bff/admin/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-13 (0.0.4 S05): governed Replay of ONE dead job. The acting account comes
// from the signed-in session via createAdminApiClient's actorAccountId (ADR-0148)
// -- the body carries the job id and nothing else, and an `actor_account_id` in
// the body is simply never read.
//
// No bulk replay in v1 (PRD default): the body is one `jobId`, not a list.
export const POST = withSession(async (req, { session }) => {
  const client = createAdminApiClient(session);
  const body = await readJsonBody(req);
  return handleReplayJobViaApi(client, body?.jobId);
});
