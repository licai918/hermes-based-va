import { createAdminApiClient, createAdminDeps } from "@/lib/bff/admin/deps";
import { handleListSlots, handleListSlotsViaApi } from "@/lib/bff/admin/knowledge";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const GET = withSession((_req, { session }) => {
  // ADR-0141/0145: list policy slots over the Supervisor Admin Profile API when
  // configured; otherwise read the in-memory store.
  const client = createAdminApiClient(session);
  if (client) return handleListSlotsViaApi(client);
  return handleListSlots(createAdminDeps(session));
});
