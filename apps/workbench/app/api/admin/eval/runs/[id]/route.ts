import { createAdminDeps } from "@/lib/bff/admin/deps";
import { handleGetRun } from "@/lib/bff/admin/eval";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const GET = withSession((_req, ctx) =>
  handleGetRun(ctx.params?.id ?? "", createAdminDeps(ctx.session)),
);
