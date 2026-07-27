import { handleContactReasonViaApi } from "@/lib/bff/copilot/cases";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const POST = withSession((req, { session, params }) =>
  handleContactReasonViaApi(req, createCopilotApiClient(session), params?.id ?? ""),
);
