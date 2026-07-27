import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { handleClearPreferenceViaApi } from "@/lib/bff/copilot/preferences";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const POST = withSession((req, { session, params }) =>
  handleClearPreferenceViaApi(req, createCopilotApiClient(session), params?.id ?? ""),
);
