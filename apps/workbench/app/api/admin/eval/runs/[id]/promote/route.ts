import { createAdminApiClient, createAdminDeps } from "@/lib/bff/admin/deps";
import { handlePromote, handlePromoteViaApi } from "@/lib/bff/admin/eval";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const POST = withSession((_req, ctx) => {
  // ADR-0141/0146: promote dispatches with actor-attributed audit when the
  // per-profile API is configured, publishing the authoring slot the run gates
  // (ADR-0146 bridge); otherwise the in-memory EvalStore.
  const runId = ctx.params?.id ?? "";
  const client = createAdminApiClient(ctx.session);
  if (client) return handlePromoteViaApi(runId, client);
  return handlePromote(runId, createAdminDeps(ctx.session));
});
