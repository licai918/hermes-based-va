import { handlePriorityViaApi } from "@/lib/bff/copilot/cases";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// Supervisor/admin only (ADR-0082) -- checked in the handler before dispatch.
export const POST = withSession((req, { session, params }) =>
  handlePriorityViaApi(req, createCopilotApiClient(session), params?.id ?? "", session),
);
