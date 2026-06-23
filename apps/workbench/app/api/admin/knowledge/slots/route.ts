import { createAdminDeps } from "@/lib/bff/admin/deps";
import { handleListSlots } from "@/lib/bff/admin/knowledge";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const GET = withSession((_req, ctx) =>
  handleListSlots(createAdminDeps(ctx.session)),
);
