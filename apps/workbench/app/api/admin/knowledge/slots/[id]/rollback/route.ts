import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { handleRollbackSlotViaApi } from "@/lib/bff/admin/knowledge";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const POST = withSession((_req, ctx) =>
  handleRollbackSlotViaApi(ctx.params?.id ?? "", createAdminApiClient(ctx.session)),
);
