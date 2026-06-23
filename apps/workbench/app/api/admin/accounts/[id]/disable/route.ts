import { handleDisableAccount } from "@/lib/bff/admin/accounts";
import { createAdminDeps } from "@/lib/bff/admin/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const POST = withSession((_req, ctx) =>
  handleDisableAccount(ctx.params?.id ?? "", createAdminDeps(ctx.session)),
);
