import { createAdminDeps } from "@/lib/bff/admin/deps";
import { handleSubmitSlot } from "@/lib/bff/admin/knowledge";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const POST = withSession((_req, ctx) =>
  handleSubmitSlot(ctx.params?.id ?? "", createAdminDeps(ctx.session)),
);
