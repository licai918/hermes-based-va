import { createAdminApiClient, createAdminDeps } from "@/lib/bff/admin/deps";
import { handleSignOff, handleSignOffViaApi } from "@/lib/bff/admin/eval";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const POST = withSession((_req, ctx) => {
  // ADR-0141/0146: sign-off dispatches with actor-attributed audit when the
  // per-profile API is configured; otherwise the in-memory EvalStore.
  const runId = ctx.params?.id ?? "";
  const client = createAdminApiClient(ctx.session);
  if (client) return handleSignOffViaApi(runId, client);
  return handleSignOff(runId, createAdminDeps(ctx.session));
});
