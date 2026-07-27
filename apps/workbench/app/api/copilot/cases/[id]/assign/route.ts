import { handleAssignViaApi } from "@/lib/bff/copilot/cases";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// ADR-0141: a governed dispatchWrite with actor-attributed audit. Supervisor/admin
// only (ADR-0082) -- the handler checks the session role before dispatching.
export const POST = withSession((req, { session, params }) =>
  handleAssignViaApi(req, createCopilotApiClient(session), params?.id ?? "", session),
);
