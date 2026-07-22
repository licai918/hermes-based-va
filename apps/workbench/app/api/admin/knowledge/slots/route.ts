import { createAdminApiClient } from "@/lib/bff/admin/deps";
import { handleListSlotsViaApi } from "@/lib/bff/admin/knowledge";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// ADR-0141/0145: the six Required Operational Policy Slots come from
// toee_knowledge_ops over the Supervisor Admin Profile API.
export const GET = withSession((_req, { session }) =>
  handleListSlotsViaApi(createAdminApiClient(session)),
);
