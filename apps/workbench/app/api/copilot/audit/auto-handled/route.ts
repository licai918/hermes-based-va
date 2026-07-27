import { handleListAutoHandledViaApi } from "@/lib/bff/copilot/audit";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const GET = withSession((_req, { session }) =>
  handleListAutoHandledViaApi(createCopilotApiClient(session)),
);
