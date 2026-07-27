import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { handleListRunsViaApi } from "@/lib/bff/admin/eval";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// ADR-0141/0146: eval runs come from toee_eval_review over the Supervisor Admin
// Profile API; the ADR-0040 gate is enforced server-side.
export const GET = withSession((_req, ctx) =>
  handleListRunsViaApi(createAdminApiClient(ctx.session)),
);
