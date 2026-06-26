import { createAdminApiClient, createAdminDeps } from "@/lib/bff/admin/deps";
import { handleSubmitSlot, handleSubmitSlotViaApi } from "@/lib/bff/admin/knowledge";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const POST = withSession((_req, ctx) => {
  // ADR-0141/0145: submit-for-eval dispatches with actor-attributed audit when the
  // per-profile API is configured; otherwise use the in-memory store.
  const slotId = ctx.params?.id ?? "";
  const client = createAdminApiClient(ctx.session);
  if (client) return handleSubmitSlotViaApi(slotId, client);
  return handleSubmitSlot(slotId, createAdminDeps(ctx.session));
});
