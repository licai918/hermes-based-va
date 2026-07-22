import { handleGetAutoHandledViaApi } from "@/lib/bff/copilot/audit";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// The acting account rides the client so the server-side audit_view entry
// (ADR-0029/0037) attributes to the supervisor who opened the detail.
export const GET = withSession((_req, { session, params }) =>
  handleGetAutoHandledViaApi(createCopilotApiClient(session), params?.id ?? ""),
);
