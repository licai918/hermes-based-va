import { createAdminDeps } from "@/lib/bff/admin/deps";
import { handleSignOff } from "@/lib/bff/admin/eval";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const POST = withSession((_req, ctx) =>
  handleSignOff(ctx.params?.id ?? "", createAdminDeps(ctx.session)),
);
