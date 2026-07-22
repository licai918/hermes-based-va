import { handleDisableAccountViaApi } from "@/lib/bff/admin/accounts";
import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const POST = withSession((_req, { session, params }) =>
  handleDisableAccountViaApi(createAdminApiClient(session), params?.id ?? ""),
);
