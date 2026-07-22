import { handleResolveViaApi } from "@/lib/bff/copilot/cases";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const POST = withSession((_req, { session, params }) =>
  handleResolveViaApi(createCopilotApiClient(session), params?.id ?? ""),
);
