import { createAdminDeps } from "@/lib/bff/admin/deps";
import { handleListRuns } from "@/lib/bff/admin/eval";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const GET = withSession((_req, ctx) =>
  handleListRuns(createAdminDeps(ctx.session)),
);
