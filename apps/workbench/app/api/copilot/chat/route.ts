import { handleChat } from "@/lib/bff/copilot/chat";
import { createCopilotDeps } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const POST = withSession((req, { session }) =>
  handleChat(req, createCopilotDeps(session)),
);
