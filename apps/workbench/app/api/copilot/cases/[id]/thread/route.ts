import { handleGetThreadViaApi } from "@/lib/bff/copilot/cases";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// The acting account rides the client so the server-side case_view audit
// (ADR-0042) attributes to it.
export const GET = withSession((_req, { session, params }) =>
  handleGetThreadViaApi(createCopilotApiClient(session), params?.id ?? ""),
);
