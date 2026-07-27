import { handleListCasesViaApi } from "@/lib/bff/copilot/cases";
import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { withSession } from "@/lib/bff/with-session";

// Node runtime: the session spine reaches node:crypto.
export const runtime = "nodejs";

// ADR-0141: the queue read is a deterministic tools:dispatch over the Internal
// Copilot Profile API; the acting account rides the client so dispatch audits
// attribute to it.
export const GET = withSession((req, { session }) =>
  handleListCasesViaApi(req, createCopilotApiClient(session), session),
);
