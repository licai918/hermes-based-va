import { handleReprobeNowViaApi } from "@/lib/bff/admin/integrations";
import { createAdminApiClient, readJsonBody } from "@/lib/bff/admin/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-25 (0.0.4 S17): on-demand health re-probe of ONE integration -- the completion
// step for BOTH reconnect shapes (the Composio OAuth return and the static-token env
// rotation). ADMIN-ONLY (withSession, path under /api/admin/integrations). Governed
// WRITE: the acting admin rides createAdminApiClient's actorAccountId (ADR-0148); the
// body carries only the integration key, never an actor.
export const POST = withSession(async (req, { session }) => {
  const client = createAdminApiClient(session);
  const body = await readJsonBody(req);
  return handleReprobeNowViaApi(client, body?.integrationKey);
});
