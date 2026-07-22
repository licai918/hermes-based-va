import { handleGetAggregateMetricsViaApi } from "@/lib/bff/admin/metrics";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-28 aggregate-metrics admin panel (0.0.3 S26). /api/admin/* is already
// admin-gated by withSession (ADR-0093). Dispatches over the Internal Copilot
// Profile API -- same precedent as admin/memory-audit and admin/agent-experience.
// Read-only.
export const GET = withSession((_req, { session }) =>
  handleGetAggregateMetricsViaApi(createCopilotApiClient(session)),
);
