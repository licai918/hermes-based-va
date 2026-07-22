import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { handleSignOffViaApi } from "@/lib/bff/admin/eval";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const POST = withSession((_req, ctx) =>
  handleSignOffViaApi(ctx.params?.id ?? "", createAdminApiClient(ctx.session)),
);
