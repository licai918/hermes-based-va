import { handleUpdateRole } from "@/lib/bff/admin/accounts";
import { createAdminDeps } from "@/lib/bff/admin/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const PATCH = withSession((req, ctx) =>
  handleUpdateRole(req, ctx.params?.id ?? "", createAdminDeps(ctx.session)),
);
