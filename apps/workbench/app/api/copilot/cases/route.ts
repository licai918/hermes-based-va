import { handleListCases } from "@/lib/bff/copilot/cases";
import { createCopilotDeps } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

// Node runtime: the copilot deps reach the session/account spine (node:crypto).
export const runtime = "nodejs";

export const GET = withSession((req, { session }) =>
  handleListCases(req, createCopilotDeps(session)),
);
