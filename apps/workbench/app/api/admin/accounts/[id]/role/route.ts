import { handleUpdateRoleViaApi } from "@/lib/bff/admin/accounts";
import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const PATCH = withSession((req, { session, params }) =>
  handleUpdateRoleViaApi(req, createAdminApiClient(session), params?.id ?? ""),
);
