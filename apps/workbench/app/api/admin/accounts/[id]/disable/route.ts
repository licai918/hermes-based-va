import {
  handleDisableAccount,
  handleDisableAccountViaApi,
} from "@/lib/bff/admin/accounts";
import { createAdminApiClient, createAdminDeps } from "@/lib/bff/admin/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const POST = withSession((_req, { session, params }) => {
  const accountId = params?.id ?? "";
  // ADR-0141: governed disable with actor-attributed audit over the per-profile API
  // when configured; otherwise the in-memory store.
  const client = createAdminApiClient(session);
  if (client) return handleDisableAccountViaApi(client, accountId);
  return handleDisableAccount(accountId, createAdminDeps(session));
});
