import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { handleGetRunViaApi } from "@/lib/bff/admin/eval";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const GET = withSession((_req, ctx) =>
  handleGetRunViaApi(ctx.params?.id ?? "", createAdminApiClient(ctx.session)),
);
