import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { handleSaveDraftViaApi } from "@/lib/bff/admin/knowledge";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const PUT = withSession((req, ctx) =>
  handleSaveDraftViaApi(req, ctx.params?.id ?? "", createAdminApiClient(ctx.session)),
);
