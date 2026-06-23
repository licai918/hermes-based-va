import { handleGetCase } from "@/lib/bff/copilot/cases";
import { createCopilotDeps } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const GET = withSession((_req, { session, params }) =>
  handleGetCase(params?.id ?? "", createCopilotDeps(session)),
);
