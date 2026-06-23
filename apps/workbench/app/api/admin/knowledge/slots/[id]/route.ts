import { createAdminDeps } from "@/lib/bff/admin/deps";
import { handleSaveDraft } from "@/lib/bff/admin/knowledge";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const PUT = withSession((req, ctx) =>
  handleSaveDraft(req, ctx.params?.id ?? "", createAdminDeps(ctx.session)),
);
