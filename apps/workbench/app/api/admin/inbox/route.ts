import { handleListInboxViaApi } from "@/lib/bff/admin/review-inbox";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-22 (0.0.5 S15): the unified review inbox read -- ONE queue over the L6 and
// L7 proposal tables plus the `review_item` store. Dispatches over the Internal
// Copilot Profile API: all three tools are allowlisted for internal_copilot
// only. Admin-gating comes from this route group (/api/admin/* + withSession's
// role check), per ADR-0093.
export const GET = withSession((_req, { session }) =>
  handleListInboxViaApi(createCopilotApiClient(session)),
);
