import { createCopilotDeps } from "@/lib/bff/copilot/deps";
import { handleDraft } from "@/lib/bff/copilot/drafts";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const POST = withSession((req, { session }) =>
  handleDraft(req, createCopilotDeps(session), "draft_sms"),
);
