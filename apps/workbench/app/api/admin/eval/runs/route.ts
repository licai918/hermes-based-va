import { createAdminApiClient, createAdminDeps } from "@/lib/bff/admin/deps";
import { handleListRuns, handleListRunsViaApi } from "@/lib/bff/admin/eval";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const GET = withSession((_req, ctx) => {
  // ADR-0141/0146: list eval runs from the per-profile API when configured;
  // otherwise the in-memory EvalStore.
  const client = createAdminApiClient(ctx.session);
  if (client) return handleListRunsViaApi(client);
  return handleListRuns(createAdminDeps(ctx.session));
});
