import {
  handleCreateAccount,
  handleCreateAccountViaApi,
  handleListAccounts,
  handleListAccountsViaApi,
} from "@/lib/bff/admin/accounts";
import { createAdminApiClient, createAdminDeps } from "@/lib/bff/admin/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const GET = withSession((_req, { session }) => {
  // ADR-0141: list accounts over the Supervisor Admin Profile API when configured;
  // otherwise read the in-memory store.
  const client = createAdminApiClient(session);
  if (client) return handleListAccountsViaApi(client);
  return handleListAccounts(createAdminDeps(session));
});

export const POST = withSession((req, { session }) => {
  // ADR-0141: the governed create dispatches with actor-attributed audit when the
  // per-profile API is configured; otherwise use the in-memory store.
  const client = createAdminApiClient(session);
  if (client) return handleCreateAccountViaApi(req, client);
  return handleCreateAccount(req, createAdminDeps(session));
});
