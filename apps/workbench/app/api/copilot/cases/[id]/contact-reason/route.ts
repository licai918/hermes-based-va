import { handleContactReason } from "@/lib/bff/copilot/cases";
import { createCopilotDeps } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

export const POST = withSession((req, { session, params }) =>
  handleContactReason(req, params?.id ?? "", createCopilotDeps(session)),
);
