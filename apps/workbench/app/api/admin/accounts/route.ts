import {
  handleCreateAccount,
  handleListAccounts,
} from "@/lib/bff/admin/accounts";
import { createAdminDeps } from "@/lib/bff/admin/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const GET = withSession((_req, ctx) =>
  handleListAccounts(createAdminDeps(ctx.session)),
);

export const POST = withSession((req, ctx) =>
  handleCreateAccount(req, createAdminDeps(ctx.session)),
);
