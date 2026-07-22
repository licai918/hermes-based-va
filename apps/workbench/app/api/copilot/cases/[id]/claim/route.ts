import { handleClaimViaApi } from "@/lib/bff/copilot/cases";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// ADR-0141: a governed dispatchWrite with actor-attributed audit.
export const POST = withSession((_req, { session, params }) =>
  handleClaimViaApi(createCopilotApiClient(session), params?.id ?? "", session),
);
