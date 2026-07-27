import { createCopilotApiClient } from "@/lib/bff/copilot/deps";
import { handleDismissProposalViaApi } from "@/lib/bff/copilot/preferences";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// S15 (FR-16/FR-17): dismissing an S14 proposal is audit-only -- no slot is written.
export const POST = withSession((req, { session, params }) =>
  handleDismissProposalViaApi(req, createCopilotApiClient(session), params?.id ?? ""),
);
