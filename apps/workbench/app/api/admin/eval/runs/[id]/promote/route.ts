import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { handlePromoteViaApi } from "@/lib/bff/admin/eval";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// Promotion publishes the authoring slot the run gates (ADR-0146 bridge).
export const POST = withSession((_req, ctx) =>
  handlePromoteViaApi(ctx.params?.id ?? "", createAdminApiClient(ctx.session)),
);
