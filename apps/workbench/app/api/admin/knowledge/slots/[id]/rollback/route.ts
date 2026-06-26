import { createAdminApiClient, createAdminDeps } from "@/lib/bff/admin/deps";
import {
  handleRollbackSlot,
  handleRollbackSlotViaApi,
} from "@/lib/bff/admin/knowledge";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const POST = withSession((_req, ctx) => {
  // ADR-0141/0145: rollback dispatches with actor-attributed audit when the
  // per-profile API is configured; otherwise use the in-memory store.
  const slotId = ctx.params?.id ?? "";
  const client = createAdminApiClient(ctx.session);
  if (client) return handleRollbackSlotViaApi(slotId, client);
  return handleRollbackSlot(slotId, createAdminDeps(ctx.session));
});
