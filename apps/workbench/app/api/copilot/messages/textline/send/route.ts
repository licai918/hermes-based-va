import { createCopilotDeps } from "@/lib/bff/copilot/deps";
import { handleTextlineSend } from "@/lib/bff/copilot/messages";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const POST = withSession((req, { session }) =>
  handleTextlineSend(req, createCopilotDeps(session)),
);
