import { handleGetRetentionStatusViaApi } from "@/lib/bff/admin/retention";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-30 (0.0.3 S28): Customer Memory retention sweep admin panel -- last run +
// per-class counts. Dispatches over the Internal Copilot Profile API, same
// precedent as admin/metrics. Read-only.
export const GET = withSession((_req, { session }) =>
  handleGetRetentionStatusViaApi(createCopilotApiClient(session)),
);
