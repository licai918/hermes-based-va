import { createAdminApiClient, createAdminDeps } from "@/lib/bff/admin/deps";
import { handleGetRun, handleGetRunViaApi } from "@/lib/bff/admin/eval";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const GET = withSession((_req, ctx) => {
  // ADR-0141/0146: read one eval run from the per-profile API when configured
  // (governed not_found -> 404); otherwise the in-memory EvalStore.
  const runId = ctx.params?.id ?? "";
  const client = createAdminApiClient(ctx.session);
  if (client) return handleGetRunViaApi(runId, client);
  return handleGetRun(runId, createAdminDeps(ctx.session));
});
