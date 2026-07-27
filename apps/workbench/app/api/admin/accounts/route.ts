import {
  handleCreateAccountViaApi,
  handleListAccountsViaApi,
} from "@/lib/bff/admin/accounts";
import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// ADR-0141: accounts live in Postgres behind the Supervisor Admin Profile API. The
// read is a dispatch; the create is a governed dispatchWrite with actor-attributed
// audit.
export const GET = withSession((_req, { session }) =>
  handleListAccountsViaApi(createAdminApiClient(session)),
);

export const POST = withSession((req, { session }) =>
  handleCreateAccountViaApi(req, createAdminApiClient(session)),
);
