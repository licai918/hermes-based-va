import { createAdminApiClient, createAdminDeps } from "@/lib/bff/admin/deps";
import { handleSaveDraft, handleSaveDraftViaApi } from "@/lib/bff/admin/knowledge";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const PUT = withSession((req, ctx) => {
  // ADR-0141/0145: the governed save-draft dispatches with actor-attributed audit
  // when the per-profile API is configured; otherwise use the in-memory store.
  const slotId = ctx.params?.id ?? "";
  const client = createAdminApiClient(ctx.session);
  if (client) return handleSaveDraftViaApi(req, slotId, client);
  return handleSaveDraft(req, slotId, createAdminDeps(ctx.session));
});
